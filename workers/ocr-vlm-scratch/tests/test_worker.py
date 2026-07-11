"""Worker OCR backend OCR-VLM from-scratch.

⚠️ Le vrai checkpoint n'est JAMAIS chargé ici (il a déjà figé une machine de
dev ; il n'a été évalué que sur Kaggle). ``_load_model`` est monkeypatché et
remplacé par un modèle factice : on teste le pré-traitement d'image, la
sérialisation du ticket, et le câblage — pas les poids.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from PIL import Image
from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError
from pricetracker_receipt_pipeline.worker import mapper

from pricetracker_ocr_vlm_scratch import main, ocr, scratch_backend
from pricetracker_ocr_vlm_scratch.config import get_settings
from pricetracker_ocr_vlm_scratch.scratch_backend import OcrVlmScratchBackend

TICKET_JSON = json.dumps(
    {
        "ticket": {
            "date": "20240315 14:30",
            "chaine_supermarche": "CARREFOUR",
            "adresse": "12 rue X",
            "produits": [{"nom_produit": "BANANES", "prix_unitaire_ou_kg": 2.15, "unites": 2}],
        }
    }
)


class _FakeBackend(OcrBackend):
    def __init__(self, output: str | Exception) -> None:
        self._output = output

    def extract_text(self, image_path: str) -> str:
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


class _FakeTicket:
    """Imite ``receipt_vlm.data.schema.Ticket`` (seul ``to_dict`` est utilisé)."""

    def to_dict(self) -> dict:
        return json.loads(TICKET_JSON)


class _FakeModel:
    def __init__(self) -> None:
        self.seen_shapes: list[tuple[int, ...]] = []

    def generate(self, pixels, **kwargs):
        self.seen_shapes.append(tuple(pixels.shape))
        return [_FakeTicket()]


@pytest.fixture
def weights_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ckpt = tmp_path / "ocr_vlm.pt"
    ckpt.write_bytes(b"x")
    tok = tmp_path / "tokenizer.json"
    tok.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RECEIPT_VLM_MODEL_PATH", str(ckpt))
    monkeypatch.setenv("RECEIPT_VLM_TOKENIZER_PATH", str(tok))
    return tmp_path


@pytest.fixture
def receipt_image(tmp_path: Path) -> str:
    path = tmp_path / "receipt.jpg"
    Image.new("RGB", (60, 120), (250, 250, 250)).save(path)
    return str(path)


def test_engine_label_default():
    assert get_settings().prt_ocr_engine_label == "ocr-vlm-scratch"


def test_run_ocr_returns_canonical_dict():
    """Le backend émet le JSON canonique → ReceiptParser court-circuite."""
    result = ocr.run_ocr(_FakeBackend(TICKET_JSON), b"fake-jpeg-bytes")

    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR"
    rows = mapper.map_prix_extraits_rows(result, "tid")
    assert rows[0]["raw_text"] == "BANANES"
    assert rows[0]["line_total"] == 4.30


def test_run_ocr_wraps_backend_failure_as_deterministic_error():
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend(OcrBackendError("inference failed")), b"bytes")


def test_backend_requires_checkpoint_env():
    with pytest.raises(OcrBackendError, match="checkpoint"):
        OcrVlmScratchBackend()


def test_backend_requires_tokenizer_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ckpt = tmp_path / "ocr_vlm.pt"
    ckpt.write_bytes(b"x")
    monkeypatch.setenv("RECEIPT_VLM_MODEL_PATH", str(ckpt))

    with pytest.raises(OcrBackendError, match="tokenizer"):
        OcrVlmScratchBackend()


def test_backend_rejects_missing_checkpoint_file(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RECEIPT_VLM_MODEL_PATH", "/nonexistent/ocr_vlm.pt")
    monkeypatch.setenv("RECEIPT_VLM_TOKENIZER_PATH", "/nonexistent/tokenizer.json")

    with pytest.raises(OcrBackendError, match="not found"):
        OcrVlmScratchBackend()


def test_extract_text_letterboxes_image_and_serialises_ticket(
    weights_on_disk: Path,
    receipt_image: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Pré-traitement réel (prepare_ocr_pixels), modèle factice."""
    fake_model = _FakeModel()
    monkeypatch.setattr(OcrVlmScratchBackend, "_load_model", lambda self: None)

    backend = OcrVlmScratchBackend()
    backend._model = fake_model

    output = backend.extract_text(receipt_image)

    # Batch (1, C=3, H=384, W=256) : canvas portrait, ratio préservé.
    assert fake_model.seen_shapes == [(1, 3, 384, 256)]
    assert json.loads(output) == json.loads(TICKET_JSON)
    assert backend.model_id == "ocr-vlm-scratch"


def test_extract_text_missing_image_raises(weights_on_disk: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(OcrVlmScratchBackend, "_load_model", lambda self: None)
    backend = OcrVlmScratchBackend()

    with pytest.raises(FileNotFoundError):
        backend.extract_text("/nonexistent/receipt.jpg")


def test_extract_text_wraps_model_failure(
    weights_on_disk: Path,
    receipt_image: str,
    monkeypatch: pytest.MonkeyPatch,
):
    class _BoomModel:
        def generate(self, pixels, **kwargs):
            raise RuntimeError("cuda oom")

    monkeypatch.setattr(OcrVlmScratchBackend, "_load_model", lambda self: None)
    backend = OcrVlmScratchBackend()
    backend._model = _BoomModel()

    with pytest.raises(OcrBackendError, match="inference failed"):
        backend.extract_text(receipt_image)


async def test_lifespan_downloads_checkpoint_and_tokenizer(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    def _fake_ensure(uri: str, dest: str) -> str:
        calls.append((uri, dest))
        return f"{dest}/{uri.rsplit('/', 1)[-1]}"

    class _FakePool:
        async def close(self) -> None:
            return None

    async def _fake_pool(_settings):
        return _FakePool()

    monkeypatch.setenv("PRT_MODEL_GCS_URI", "gs://models/vlm/ocr-vlm-scratch/v1/ocr_vlm.pt")
    monkeypatch.setenv("PRT_TOKENIZER_GCS_URI", "gs://models/vlm/ocr-vlm-scratch/v1/tokenizer.json")
    monkeypatch.setenv("PRT_MODEL_LOCAL_DIR", "/tmp/models")
    get_settings.cache_clear()
    monkeypatch.setattr(main.weights, "ensure_weights", _fake_ensure)
    monkeypatch.setattr(main.ocr, "build_backend", lambda: "backend-sentinel")
    monkeypatch.setattr(main.pg, "create_pool", _fake_pool)

    app = FastAPI()
    async with main.lifespan(app):
        assert app.state.backend == "backend-sentinel"

    assert calls == [
        ("gs://models/vlm/ocr-vlm-scratch/v1/ocr_vlm.pt", "/tmp/models"),
        ("gs://models/vlm/ocr-vlm-scratch/v1/tokenizer.json", "/tmp/models"),
    ]
    assert os.environ["RECEIPT_VLM_MODEL_PATH"] == "/tmp/models/ocr_vlm.pt"
    assert os.environ[scratch_backend.ENV_TOKENIZER_PATH] == "/tmp/models/tokenizer.json"
