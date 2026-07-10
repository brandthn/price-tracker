"""Worker OCR backend receipt-vlm-500m — câblage + garde-fous du provider.

Le modèle n'est jamais chargé ici (torch/transformers ne sont pas sollicités) :
seul le contrat du provider (mode JSON, checkpoint présent) est vérifié.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError
from pricetracker_receipt_pipeline.worker import mapper

from pricetracker_ocr_vlm_receipt import main, ocr
from pricetracker_ocr_vlm_receipt.config import get_settings
from pricetracker_ocr_vlm_receipt.receipt_vlm_provider import ReceiptVlmProvider

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


def test_engine_label_default():
    assert get_settings().prt_ocr_engine_label == "receipt-vlm-500m"


def test_run_ocr_returns_canonical_dict():
    """Le modèle émet déjà le JSON canonique → ReceiptParser court-circuite."""
    result = ocr.run_ocr(_FakeBackend(TICKET_JSON), b"fake-jpeg-bytes")

    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR"
    rows = mapper.map_prix_extraits_rows(result, "tid")
    assert rows[0]["raw_text"] == "BANANES"
    assert rows[0]["line_total"] == 4.30


def test_run_ocr_wraps_backend_failure_as_deterministic_error():
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend(OcrBackendError("inference failed")), b"bytes")


def test_provider_requires_json_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"x")
    monkeypatch.setenv("RECEIPT_VLM_MODEL_PATH", str(ckpt))
    monkeypatch.setenv("RECEIPT_VLM_MODE", "transcribe")

    with pytest.raises(OcrBackendError, match="json"):
        ReceiptVlmProvider()


def test_provider_requires_existing_checkpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RECEIPT_VLM_MODE", "json")
    monkeypatch.setenv("RECEIPT_VLM_MODEL_PATH", "/nonexistent/model.pt")

    with pytest.raises(OcrBackendError, match="not found"):
        ReceiptVlmProvider()


def test_provider_builds_without_loading_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Le checkpoint est validé au démarrage, le modèle chargé au 1er analyze."""
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"x")
    monkeypatch.setenv("RECEIPT_VLM_MODE", "json")
    monkeypatch.setenv("RECEIPT_VLM_MODEL_PATH", str(ckpt))

    backend = ocr.build_backend()

    assert backend.active_model == "receipt-vlm-500m"
    assert backend.active_mode == "json"


async def test_lifespan_downloads_checkpoint_and_sets_model_path(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    def _fake_ensure(uri: str, dest: str) -> str:
        calls.append((uri, dest))
        return f"{dest}/receipt_vlm_500m_merged.pt"

    class _FakePool:
        async def close(self) -> None:
            return None

    async def _fake_pool(_settings):
        return _FakePool()

    monkeypatch.setenv("PRT_MODEL_GCS_URI", "gs://models/vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt")
    monkeypatch.setenv("PRT_MODEL_LOCAL_DIR", "/tmp/models")
    get_settings.cache_clear()
    monkeypatch.setattr(main.weights, "ensure_weights", _fake_ensure)
    monkeypatch.setattr(main.ocr, "build_backend", lambda: "backend-sentinel")
    monkeypatch.setattr(main.pg, "create_pool", _fake_pool)

    app = FastAPI()
    async with main.lifespan(app):
        assert app.state.backend == "backend-sentinel"

    assert calls == [
        ("gs://models/vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt", "/tmp/models")
    ]
    assert os.environ["RECEIPT_VLM_MODEL_PATH"] == "/tmp/models/receipt_vlm_500m_merged.pt"
