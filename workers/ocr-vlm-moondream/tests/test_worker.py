"""Worker OCR backend Moondream — câblage backend/parser/mapper + bootstrap poids."""

from __future__ import annotations

import json
import os

import pytest
from fastapi import FastAPI
from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import ReceiptParseError
from pricetracker_receipt_pipeline.worker import mapper

from pricetracker_ocr_vlm_moondream import main, ocr
from pricetracker_ocr_vlm_moondream.config import get_settings

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
    assert get_settings().prt_ocr_engine_label == "moondream-0.5b"


def test_run_ocr_returns_canonical_dict():
    result = ocr.run_ocr(_FakeBackend(TICKET_JSON), b"fake-jpeg-bytes")

    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR"
    rows = mapper.map_prix_extraits_rows(result, "tid")
    assert rows[0]["raw_text"] == "BANANES"
    assert rows[0]["line_total"] == 4.30


def test_run_ocr_wraps_parse_failure_as_deterministic_error():
    """→ 204 ACK côté /push : inutile de rejouer une image illisible."""
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend(ReceiptParseError("no text")), b"bytes")


async def _run_lifespan(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Exécute le lifespan avec backend/pool mockés ; retourne les appels weights."""
    calls: list[tuple[str, str]] = []

    def _fake_ensure(uri: str, dest: str) -> str:
        calls.append((uri, dest))
        return f"{dest}/moondream.mf"

    class _FakePool:
        async def close(self) -> None:
            return None

    monkeypatch.setattr(main.weights, "ensure_weights", _fake_ensure)
    monkeypatch.setattr(main.ocr, "build_backend", lambda: "backend-sentinel")

    async def _fake_pool(_settings):
        return _FakePool()

    monkeypatch.setattr(main.pg, "create_pool", _fake_pool)

    app = FastAPI()
    async with main.lifespan(app):
        assert app.state.backend == "backend-sentinel"
    return calls


async def test_lifespan_downloads_weights_and_sets_model_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRT_MODEL_GCS_URI", "gs://models/vlm/moondream/v1/moondream.mf")
    monkeypatch.setenv("PRT_MODEL_LOCAL_DIR", "/tmp/models")
    get_settings.cache_clear()

    calls = await _run_lifespan(monkeypatch)

    assert calls == [("gs://models/vlm/moondream/v1/moondream.mf", "/tmp/models")]
    assert os.environ["RECEIPT_VLM_MODEL_PATH"] == "/tmp/models/moondream.mf"


async def test_lifespan_skips_bootstrap_when_uri_unset(monkeypatch: pytest.MonkeyPatch):
    """Dev local : RECEIPT_VLM_MODEL_PATH déjà posé, pas de download."""
    get_settings.cache_clear()

    calls = await _run_lifespan(monkeypatch)

    assert calls == []
