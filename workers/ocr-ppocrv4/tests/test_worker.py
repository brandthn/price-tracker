"""Worker OCR backend PP-OCRv4 mobile — câblage backend/parser/mapper.

Le backend réel n'est jamais chargé ici : il est remplacé par un faux qui rend
le texte brut qu'aurait produit l'OCR.
"""

from __future__ import annotations

import pytest
from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError
from pricetracker_receipt_pipeline.worker import mapper

from pricetracker_ocr_ppocrv4 import ocr
from pricetracker_ocr_ppocrv4.config import get_settings

OCR_TEXT = """\
INTERMARCHE
5 avenue des Lilas
69003 Lyon

02/04/2024 09:05

YAOURT NATURE            1,29 €
CAFE MOULU               3,40 €

TOTAL TTC                4,69 €
"""


class _FakeBackend(OcrBackend):
    def __init__(self, output: str | Exception) -> None:
        self._output = output

    def extract_text(self, image_path: str) -> str:
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


def test_engine_label_default():
    assert get_settings().prt_ocr_engine_label == "ppocrv4"


def test_run_ocr_parses_raw_ocr_text():
    result = ocr.run_ocr(_FakeBackend(OCR_TEXT), b"fake-jpeg-bytes")

    ticket = result["ticket"]
    assert ticket["chaine_supermarche"] == "INTERMARCHE"
    assert ticket["date"] == "20240402 09:05"

    rows = mapper.map_prix_extraits_rows(result, "tid")
    assert [r["raw_text"] for r in rows] == ["YAOURT NATURE", "CAFE MOULU"]
    assert rows[1]["unit_price"] == 3.40


def test_map_ticket_fields_totals():
    result = ocr.run_ocr(_FakeBackend(OCR_TEXT), b"bytes")
    fields = mapper.map_ticket_fields(result, "tid", "obj.jpg", "ppocrv4", 42, 1.0)

    assert fields["enseigne"] == "INTERMARCHE"
    assert fields["total_amount"] == 4.69
    assert fields["ocr_engine"] == "ppocrv4"


def test_run_ocr_wraps_backend_failure_as_deterministic_error():
    """→ 204 ACK côté /push : inutile de rejouer une image illisible."""
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend(OcrBackendError("ppocrv4 failed")), b"bytes")


def test_run_ocr_empty_text_is_deterministic_error():
    with pytest.raises(ocr.OcrProcessingError):
        ocr.run_ocr(_FakeBackend("   "), b"bytes")
