"""Live Groq API integration — requires API key and receipt images on disk."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from receipt_ocr import extract_receipt, reset_default_backend
from receipt_ocr.backends.vlm.groq_provider import resolve_groq_api_key
from receipt_ocr.constants import (
    ENV_VLM_MODE,
    ENV_VLM_MODEL,
    ProductField,
    TicketField,
    VlmModelName,
    VlmMode,
)
from receipt_ocr.env import load_project_env

ROOT = Path(__file__).resolve().parent.parent
LOCAL_RECEIPTS_DIR = ROOT / "data" / "raw" / "images_tickets_caisse"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
_DATE_RE = re.compile(r"^\d{8} \d{2}:\d{2}$")


def _local_images() -> list[Path]:
    if not LOCAL_RECEIPTS_DIR.is_dir():
        return []
    return sorted(
        p
        for p in LOCAL_RECEIPTS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def pytest_generate_tests(metafunc):
    if "receipt_image" not in metafunc.fixturenames:
        return
    max_images = metafunc.config.getoption("--integration-max-images", default=3)
    images = _local_images()
    if max_images > 0:
        images = images[:max_images]
    if not images:
        metafunc.parametrize(
            "receipt_image",
            [pytest.param(None, marks=pytest.mark.skip(reason="no local receipt images"))],
            ids=["no-image"],
        )
    else:
        metafunc.parametrize(
            "receipt_image",
            images,
            ids=[p.name for p in images],
        )


@pytest.fixture(autouse=True)
def _groq_env(monkeypatch):
    load_project_env()
    monkeypatch.setenv("RECEIPT_OCR_BACKEND", "vlm")
    monkeypatch.setenv(ENV_VLM_MODEL, VlmModelName.GROQ_LLAMA4_SCOUT.value)
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.JSON.value)
    reset_default_backend()
    yield
    reset_default_backend()


@pytest.mark.integration
@pytest.mark.groq
def test_groq_extract_receipt_schema(receipt_image: Path):
    """Call Groq vision API and assert README-compatible output."""
    resolve_groq_api_key()

    result = extract_receipt(str(receipt_image))

    assert TicketField.TICKET.value in result
    ticket = result[TicketField.TICKET.value]
    assert TicketField.DATE.value in ticket
    assert TicketField.CHAINE.value in ticket
    assert TicketField.ADRESSE.value in ticket
    assert TicketField.PRODUITS.value in ticket

    date_value = ticket[TicketField.DATE.value]
    assert isinstance(date_value, str)
    if date_value:
        assert _DATE_RE.match(date_value), f"unexpected date format: {date_value!r}"

    products = ticket[TicketField.PRODUITS.value]
    assert isinstance(products, list)

    for product in products:
        assert ProductField.NOM.value in product
        assert ProductField.PRIX.value in product
        assert ProductField.UNITES.value in product
        assert isinstance(product[ProductField.NOM.value], str)
        assert isinstance(product[ProductField.PRIX.value], (int, float))
        assert isinstance(product[ProductField.UNITES.value], int)
        assert product[ProductField.UNITES.value] >= 1

    chain = ticket[TicketField.CHAINE.value]
    assert isinstance(chain, str)
    assert chain or products, "expected store name or at least one product"
