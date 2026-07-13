"""Tests sur les vraies photos de tickets du disque.

Par défaut on ne prend que images_tickets_caisse/, et seulement 3 images. Le cache
Kaggle (environ 370 images) n'entre pas dans la danse sans --integration-all-data :
une OCR par image, ça se compte en heures sur un laptop.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from receipt_ocr import extract_receipt
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw"
LOCAL_RECEIPTS_DIR = DATA_DIR / "images_tickets_caisse"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def _images_in_dir(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def _images_from_kaggle_cache() -> list[Path]:
    images: list[Path] = []
    if not DATA_DIR.exists():
        return images
    for pointer in DATA_DIR.rglob("KAGGLEHUB_PATH.txt"):
        cache_dir = Path(pointer.read_text(encoding="utf-8").strip())
        if cache_dir.is_dir():
            images.extend(
                p for p in cache_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS
            )
    return sorted(images)


def _gather_images(include_all_data: bool) -> list[Path]:
    images = _images_in_dir(LOCAL_RECEIPTS_DIR)
    if include_all_data:
        images = sorted(set(images) | set(_images_from_kaggle_cache()))
    return images


def _apply_max_images(images: list[Path], max_images: int) -> list[Path]:
    if max_images <= 0:
        return images
    return images[:max_images]


def pytest_generate_tests(metafunc):
    """Paramètre les tests avec une liste d'images plafonnée dès la collecte."""
    if "image_path" not in metafunc.fixturenames:
        return

    include_all = metafunc.config.getoption("--integration-all-data", default=False)
    max_images = metafunc.config.getoption("--integration-max-images", default=3)
    images = _apply_max_images(_gather_images(include_all), max_images)

    if not images:
        metafunc.parametrize(
            "image_path",
            [pytest.param(None, marks=pytest.mark.skip(reason="no images"))],
            ids=["no-image"],
        )
    else:
        metafunc.parametrize(
            "image_path",
            images,
            ids=lambda p: p.name,
        )


@pytest.fixture(scope="session")
def paddle_backend():
    """Un seul backend pour toute la session : recharger les poids coûte trop cher."""
    try:
        return PaddleOcrBackend()
    except ImportError:
        pytest.skip("PaddleOCR is not installed in this environment.")


@pytest.mark.integration
def test_extract_receipt_returns_valid_schema(
    image_path: Path,
    paddle_backend: PaddleOcrBackend,
) -> None:
    """OCR + parsing sur une vraie image doit rendre le schéma attendu."""
    result = extract_receipt(str(image_path), backend=paddle_backend)

    assert "ticket" in result, f"Missing 'ticket' key for {image_path.name}"
    ticket = result["ticket"]
    assert {"date", "chaine_supermarche", "adresse", "produits"} <= ticket.keys()
    assert isinstance(ticket["produits"], list)

    for product in ticket["produits"]:
        assert "nom_produit" in product
        assert "prix_unitaire_ou_kg" in product
        assert "unites" in product
        assert isinstance(product["prix_unitaire_ou_kg"], float)
        assert isinstance(product["unites"], int)
        assert product["unites"] >= 1
