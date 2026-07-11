"""Worker OCR backend Groq — câblage backend/parser/mapper, sans appel réseau."""

from __future__ import annotations

import json

import pytest
from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError
from pricetracker_receipt_pipeline.worker import mapper

from pricetracker_ocr_vlm_groq import ocr
from pricetracker_ocr_vlm_groq.config import get_settings

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
    assert get_settings().prt_ocr_engine_label == "groq-llama4-scout"


def test_run_ocr_returns_canonical_dict():
    result = ocr.run_ocr(_FakeBackend(TICKET_JSON), b"fake-jpeg-bytes")

    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR"
    rows = mapper.map_prix_extraits_rows(result, "tid")
    assert rows[0]["raw_text"] == "BANANES"
    assert rows[0]["quantity"] == 2.0
    assert rows[0]["line_total"] == 4.30
    assert rows[0]["needs_validation"] is True


def test_run_ocr_wraps_backend_failure_as_deterministic_error():
    """→ 204 ACK côté /push : inutile de rejouer une image illisible."""
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend(OcrBackendError("bad image")), b"bytes")


def test_groq_provider_requires_json_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("RECEIPT_VLM_MODE", "transcribe")
    with pytest.raises(OcrBackendError, match="json"):
        ocr.build_backend()


def test_build_backend_wires_groq_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("RECEIPT_VLM_MODE", "json")

    backend = ocr.build_backend()

    assert backend.active_model == "groq-llama4-scout"
    assert backend.active_mode == "json"
