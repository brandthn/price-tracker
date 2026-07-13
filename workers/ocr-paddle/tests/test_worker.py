"""Worker OCR backend PaddleOCR — câblage backend/parser/mapper.

Le backend réel n'est jamais chargé ici : ``PaddleOcrBackend`` est remplacé par
un faux qui rend le texte brut qu'aurait produit l'OCR.
"""

from __future__ import annotations

import pytest
from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError
from pricetracker_receipt_pipeline.worker import mapper

from pricetracker_ocr_paddle import ocr
from pricetracker_ocr_paddle.config import get_settings

OCR_TEXT = """\
CARREFOUR MARKET
12 rue de la République
75001 Paris

15/03/2024 14:30

BANANES BIO              2,15 €
PAIN COMPLET             1,20 €

TOTAL TTC                3,35 €
"""


class _FakeBackend(OcrBackend):
    def __init__(self, output: str | Exception) -> None:
        self._output = output

    def extract_text(self, image_path: str) -> str:
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


def test_engine_label_default():
    assert get_settings().prt_ocr_engine_label == "paddleocr"


def test_run_ocr_parses_raw_ocr_text():
    result = ocr.run_ocr(_FakeBackend(OCR_TEXT), b"fake-jpeg-bytes")

    ticket = result["ticket"]
    assert ticket["chaine_supermarche"] == "CARREFOUR MARKET"
    assert ticket["date"] == "20240315 14:30"

    rows = mapper.map_prix_extraits_rows(result, "tid")
    assert [r["raw_text"] for r in rows] == ["BANANES BIO", "PAIN COMPLET"]
    assert rows[0]["unit_price"] == 2.15
    assert rows[0]["needs_validation"] is True


def test_map_ticket_fields_totals():
    result = ocr.run_ocr(_FakeBackend(OCR_TEXT), b"bytes")
    fields = mapper.map_ticket_fields(result, "paddleocr", 42, 1.0)

    assert fields["enseigne"] == "CARREFOUR MARKET"
    assert fields["total_amount"] == 3.35
    assert fields["ocr_engine"] == "paddleocr"


def test_run_ocr_wraps_backend_failure_as_deterministic_error():
    """→ 204 ACK côté /push : inutile de rejouer une image illisible."""
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend(OcrBackendError("paddle failed")), b"bytes")


def test_run_ocr_empty_text_is_deterministic_error():
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend("   "), b"bytes")
