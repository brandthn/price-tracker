"""Backend OCR-VLM « from scratch » (encodeur + décodeur maison, sans CLIP ni LLM).

Le modèle (:class:`receipt_vlm.models.ocr_vlm.OcrVLM`) ne prend aucun prompt et
décode directement un ticket canonique : il implémente donc :class:`OcrBackend`
en direct, sans passer par ``VlmBackend`` / ``VlmProvider`` (pas de prompts,
pas d'escalade de crop, pas de retries).

La recette d'inférence reproduit ``dev_ocr/vlm_training/scripts/evaluate_ocr_vlm.py`` :
``CharTokenizer.load`` → ``OcrVLM.from_checkpoint`` → ``prepare_ocr_pixels`` →
``generate`` → ``Ticket.to_dict()`` → JSON. Le JSON canonique traverse ensuite
``ReceiptParser.parse_text`` (branche ``try_parse_vlm_json``) sans modification.

Torch et ``receipt_vlm`` sont importés paresseusement (dans ``__init__``) pour
que le module reste importable sans eux, comme les backends de ``dev_ocr``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.constants import ENV_VLM_MODEL_PATH
from pricetracker_receipt_pipeline.exceptions import OcrBackendError

ENV_TOKENIZER_PATH = "RECEIPT_VLM_TOKENIZER_PATH"
"""Chemin local du ``tokenizer*.json`` (posé par le bootstrap des poids)."""


def _resolve_path(explicit: str | None, env_var: str, label: str) -> Path:
    raw = (explicit or os.environ.get(env_var, "")).strip().strip('"').strip("'")
    if not raw:
        raise OcrBackendError(
            f"OcrVlmScratchBackend needs a {label}. Set {env_var} "
            "(posé par le bootstrap PRT_MODEL_GCS_URI / PRT_TOKENIZER_GCS_URI)."
        )
    path = Path(raw)
    if not path.is_file():
        raise OcrBackendError(f"{label.capitalize()} not found: {path}")
    return path


class OcrVlmScratchBackend(OcrBackend):
    """Inférence locale CPU du modèle OCR-VLM entraîné from scratch."""

    def __init__(
        self,
        checkpoint_path: str | None = None,
        tokenizer_path: str | None = None,
        device: str = "cpu",
        max_len: int | None = None,
    ) -> None:
        self._checkpoint = _resolve_path(checkpoint_path, ENV_VLM_MODEL_PATH, "checkpoint")
        self._tokenizer_path = _resolve_path(tokenizer_path, ENV_TOKENIZER_PATH, "tokenizer")
        self._device = device
        self._max_len = max_len
        self._model: Any = None
        self._load_model()

    @property
    def model_id(self) -> str:
        return "ocr-vlm-scratch"

    def _load_model(self) -> None:
        try:
            from receipt_vlm.data.tokenizer import CharTokenizer
            from receipt_vlm.models.ocr_vlm import OcrVLM
        except ImportError as exc:
            raise ImportError(
                "OcrVlmScratchBackend requires torch and the receipt_vlm package "
                "(tous deux déclarés dans le pyproject.toml de ce worker)."
            ) from exc

        try:
            tokenizer = CharTokenizer.load(self._tokenizer_path)
            self._model = OcrVLM.from_checkpoint(
                str(self._checkpoint), tokenizer, device=self._device
            )
        except Exception as exc:
            raise OcrBackendError(
                f"Failed to load the from-scratch OCR-VLM checkpoint "
                f"{self._checkpoint}: {exc}"
            ) from exc

    def extract_text(self, image_path: str) -> str:
        """Retourne le ticket canonique sérialisé en JSON (pas du texte OCR brut)."""
        path = self._validate_image_path(image_path)

        import torch
        from PIL import Image

        from receipt_vlm.data.ocr_transform import prepare_ocr_pixels

        try:
            with Image.open(path) as image:
                pixels = prepare_ocr_pixels(image)
            batch = torch.from_numpy(pixels).unsqueeze(0).to(self._device)

            generate_kwargs = {"max_len": self._max_len} if self._max_len else {}
            tickets = self._model.generate(batch, **generate_kwargs)
        except Exception as exc:
            raise OcrBackendError(
                f"From-scratch OCR-VLM inference failed on {image_path!r}: {exc}"
            ) from exc

        if not tickets:
            raise OcrBackendError("From-scratch OCR-VLM returned no ticket.")
        return json.dumps(tickets[0].to_dict(), ensure_ascii=False)
