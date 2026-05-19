"""Integration tests against real receipt images on disk.

These tests run only when:

* :file:`data/raw/` contains at least one image, **and**
* the user did not pass ``--no-integration``.

Otherwise they are skipped automatically by the root ``conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from receipt_ocr import extract_receipt
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def _gather_images() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return [p for p in DATA_DIR.rglob("*") if p.suffix.lower() in IMAGE_EXTS]


REAL_IMAGES = _gather_images()


@pytest.mark.integration
@pytest.mark.parametrize(
    "image_path",
    REAL_IMAGES or [pytest.param(None, marks=pytest.mark.skip(reason="no images"))],
    ids=lambda p: p.name if p else "no-image",
)
def test_extract_receipt_returns_schema_on_real_images(image_path: Path) -> None:
    try:
        backend = PaddleOcrBackend()
    except ImportError:
        pytest.skip("PaddleOCR is not installed in this environment.")

    result = extract_receipt(str(image_path), backend=backend)

    assert "ticket" in result
    ticket = result["ticket"]
    assert {"date", "chaine_supermarche", "adresse", "produits"} <= ticket.keys()
    assert isinstance(ticket["produits"], list)
