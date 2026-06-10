"""Local inference provider for the hybrid CLIP+SmolLM receipt VLM.

Loads a merged checkpoint (LoRA folded via ``LoRALinear.merge_weights`` by
``vlm_training/scripts/export_checkpoint.py``) from ``RECEIPT_VLM_MODEL_PATH``
and lazy-loads it on the first ``analyze`` call. The model emits the canonical
JSON directly under grammar-constrained decoding; parsing / validation /
retries stay in :mod:`receipt_ocr.backends.vlm.extraction` exactly as for the
Groq and Moondream providers.

The heavy dependencies (``torch``, ``transformers``) and the model code
(``receipt_vlm`` from ``dev_ocr/vlm_training``) are optional extras — install
with ``pip install -r requirements-receipt-vlm.txt`` — and are imported lazily
so the base ``receipt_ocr`` install stays lightweight.

Note: the model was trained on a fixed instruction, so the ``prompt`` argument
required by the :class:`VlmProvider` interface is accepted but ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.extraction import load_vlm_mode
from receipt_ocr.constants import (
    ENV_VLM_MODE,
    ENV_VLM_MODEL_PATH,
    VlmModelName,
    VlmMode,
)
from receipt_ocr.exceptions import OcrBackendError
from receipt_ocr.vlm_image_prep import (
    VlmImageConfig,
    cleanup_temp_files,
    load_vlm_image_config_from_env,
    prepare_vlm_image,
)


def _require_json_vlm_mode() -> None:
    mode = load_vlm_mode()
    if mode != VlmMode.JSON.value:
        raise OcrBackendError(
            f"ReceiptVlmProvider requires {ENV_VLM_MODE}={VlmMode.JSON.value!r} "
            f"(got {mode!r}). The model is trained end-to-end for JSON emission; "
            "transcribe and multipass modes are not supported."
        )


def resolve_checkpoint_path(model_path: str | None = None) -> str:
    """Return the merged checkpoint path from arg or ``RECEIPT_VLM_MODEL_PATH``."""
    raw = model_path or os.environ.get(ENV_VLM_MODEL_PATH, "")
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        raise OcrBackendError(
            f"ReceiptVlmProvider needs a merged checkpoint. Set {ENV_VLM_MODEL_PATH} "
            "to the .pt file produced by vlm_training/scripts/export_checkpoint.py."
        )
    path = Path(raw)
    if not path.is_file():
        raise OcrBackendError(f"Receipt VLM checkpoint not found: {path}")
    return str(path)


class ReceiptVlmProvider(VlmProvider):
    """Local inference for the hybrid CLIP+SmolLM receipt VLM (JSON mode only)."""

    def __init__(
        self,
        model_path: str | None = None,
        device: str | None = None,
        image_config: VlmImageConfig | None = None,
    ) -> None:
        _require_json_vlm_mode()
        self._model_id = VlmModelName.RECEIPT_VLM_500M.value
        self._model_path = resolve_checkpoint_path(model_path)
        self._device = device
        self._image_config = image_config or load_vlm_image_config_from_env()
        self._model: object | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def _get_model(self) -> object:
        if self._model is not None:
            return self._model
        try:
            import torch

            from receipt_vlm.models.vlm import ReceiptVLM
        except ImportError as exc:
            raise ImportError(
                "ReceiptVlmProvider requires torch/transformers and the "
                "receipt_vlm package. Install with: "
                "pip install -r requirements-receipt-vlm.txt "
                "&& pip install -e vlm_training"
            ) from exc

        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = ReceiptVLM.from_merged_checkpoint(
            self._model_path, device=self._device
        )
        return self._model

    def analyze(self, image_path: str, prompt: str) -> str:
        return self.analyze_with_options(image_path, prompt, crop_mode=None)

    def analyze_with_options(
        self,
        image_path: str,
        prompt: str,  # noqa: ARG002 — fixed-instruction model, see module docstring
        *,
        crop_mode: str | None = None,
    ) -> str:
        path = OcrBackend._validate_image_path(image_path)
        inference_path, temp_files = prepare_vlm_image(
            path,
            self._image_config,
            crop_mode_override=crop_mode,
        )
        try:
            return self._infer(inference_path)
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"Receipt VLM inference failed on {image_path!r}: {exc}"
            ) from exc
        finally:
            cleanup_temp_files(temp_files)

    def _infer(self, image_path: str) -> str:
        model = self._get_model()

        import torch
        from PIL import Image

        from receipt_vlm.data.augmentation import clip_normalize_pil

        with Image.open(image_path) as image:
            pixels = clip_normalize_pil(image)
        batch = torch.from_numpy(pixels).unsqueeze(0).to(self._device)
        outputs = model.generate(batch, constrained=True)
        return outputs[0].strip()
