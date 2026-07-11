"""Tests for CORD/SROIE schema mapping and the real-photos loader."""

import json

import pytest

from receipt_vlm.data.cord_adapter import _parse_price, ticket_from_cord_ground_truth
from receipt_vlm.data.real_photos import freeze_splits, load_real_samples
from receipt_vlm.data.sroie_adapter import normalize_sroie_date, ticket_from_sroie_entities


# --- CORD -------------------------------------------------------------------

def test_cord_price_parsing() -> None:
    assert _parse_price("2,000") == 2000.0
    assert _parse_price("12.000") == 12000.0
    assert _parse_price("3.50") == 3.5
    assert _parse_price("3,50") == 3.5
    assert _parse_price(4) == 4.0
    assert _parse_price("n/a") is None
    assert _parse_price(None) is None


def test_cord_ground_truth_mapping() -> None:
    gt = json.dumps(
        {
            "gt_parse": {
                "menu": [
                    {"nm": "ICE AMERICANO", "cnt": "2", "price": "9,000"},
                    {"nm": "CHEESE CAKE", "price": "6,500"},
                    {"nm": "", "price": "1,000"},
                    {"nm": "NO PRICE ITEM"},
                ],
                "total": {"total_price": "15,500"},
            }
        }
    )
    ticket = ticket_from_cord_ground_truth(gt)
    assert len(ticket.produits) == 2
    assert ticket.produits[0].nom_produit == "ICE AMERICANO"
    assert ticket.produits[0].unites == 2
    assert ticket.produits[0].prix_unitaire_ou_kg == 9000.0
    assert ticket.chaine_supermarche == ""  # lossy by design


def test_cord_single_menu_dict() -> None:
    ticket = ticket_from_cord_ground_truth(
        {"gt_parse": {"menu": {"nm": "LATTE", "price": "4,500"}}}
    )
    assert len(ticket.produits) == 1


# --- SROIE ------------------------------------------------------------------

def test_sroie_date_normalization() -> None:
    assert normalize_sroie_date("15/03/2024") == "20240315 00:00"
    assert normalize_sroie_date("2024-03-15") == "20240315 00:00"
    assert normalize_sroie_date("15.03.24") == "20240315 00:00"
    assert normalize_sroie_date("garbage") == ""
    assert normalize_sroie_date("") == ""


def test_sroie_entity_mapping() -> None:
    ticket = ticket_from_sroie_entities(
        {
            "company": "TESCO STORES",
            "date": "15/03/2024",
            "address": "JALAN SS6, PETALING JAYA",
            "total": "45.80",
        }
    )
    assert ticket.chaine_supermarche == "TESCO STORES"
    assert ticket.date == "20240315 00:00"
    assert ticket.adresse.startswith("JALAN")
    assert ticket.produits == []  # SROIE has no product annotations


# --- real photos -------------------------------------------------------------

@pytest.fixture()
def real_layout(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    images = tmp_path / "images"
    labels = tmp_path / "labels"
    images.mkdir()
    labels.mkdir()
    names = []
    for i in range(4):
        name = f"ticket_{i}.jpg"
        Image.new("RGB", (50, 80), "white").save(images / name)
        (labels / f"ticket_{i}.json").write_text(
            json.dumps({"ticket": {
                "date": "", "chaine_supermarche": f"Store {i}",
                "adresse": "", "produits": [],
            }}),
            encoding="utf-8",
        )
        names.append(name)
    return images, labels, names


def test_load_real_samples_no_split(real_layout) -> None:
    images, labels, _ = real_layout
    samples = load_real_samples(images, labels)
    assert len(samples) == 4
    assert samples[0].ticket.chaine_supermarche == "Store 0"


def test_freeze_splits_and_reviewed_filter(real_layout) -> None:
    images, labels, names = real_layout
    splits = freeze_splits(names, labels, test_fraction=0.25, val_fraction=0.25)
    assert sorted(splits["train"] + splits["val"] + splits["test"]) == sorted(names)

    # Refuses to overwrite frozen splits.
    with pytest.raises(FileExistsError):
        freeze_splits(names, labels)

    # Test split requires reviewed labels (none reviewed yet → empty).
    assert load_real_samples(images, labels, split="test") == []

    reviewed = {name: {"reviewed": True} for name in splits["test"]}
    (labels / "review_status.json").write_text(json.dumps(reviewed), encoding="utf-8")
    assert len(load_real_samples(images, labels, split="test")) == len(splits["test"])

    # Train split works without review flags.
    assert len(load_real_samples(images, labels, split="train")) == len(splits["train"])
