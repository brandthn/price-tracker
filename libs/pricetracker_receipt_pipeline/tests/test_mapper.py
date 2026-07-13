"""Mapping dict canonique → rows Cloud SQL."""

from __future__ import annotations

from datetime import date

from pricetracker_receipt_pipeline.worker import mapper

TICKET = {
    "ticket": {
        "date": "20240315 14:30",
        "chaine_supermarche": "  CARREFOUR  ",
        "adresse": "12 rue X",
        "produits": [
            {"nom_produit": "BANANES", "prix_unitaire_ou_kg": 2.15, "unites": 1},
            {"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.05, "unites": 3},
        ],
    }
}


def test_map_ticket_fields():
    fields = mapper.map_ticket_fields(TICKET, "paddleocr", 1234, 1.0)

    assert fields["enseigne"] == "CARREFOUR"
    assert fields["ticket_date"] == date(2024, 3, 15)
    assert fields["total_amount"] == 5.30  # 2.15 + 3×1.05
    assert fields["ocr_engine"] == "paddleocr"
    assert fields["ocr_duration_ms"] == 1234


def test_map_ticket_fields_without_products_or_date():
    fields = mapper.map_ticket_fields(
        {"ticket": {"date": "", "chaine_supermarche": "", "produits": []}},
        "paddleocr", 1, 1.0,
    )
    assert fields["enseigne"] is None
    assert fields["ticket_date"] is None
    assert fields["total_amount"] is None


def test_map_prix_extraits_rows():
    rows = mapper.map_prix_extraits_rows(TICKET, "tid")

    assert [r["line_index"] for r in rows] == [0, 1]
    assert rows[1] == {
        "ticket_id": "tid",
        "line_index": 1,
        "raw_text": "LAIT",
        "quantity": 3.0,
        "unit_price": 1.05,
        "line_total": 3.15,
        "ean": None,
        "match_method": "none",
        "match_confidence": None,
        "needs_validation": True,
        "validated_by_user": False,
    }


def test_map_prix_extraits_skips_junk_items():
    ticket = {
        "ticket": {
            "produits": [
                "not-a-dict",
                {"nom_produit": "   ", "prix_unitaire_ou_kg": 1.0, "unites": 1},
                {"nom_produit": "OK", "prix_unitaire_ou_kg": None, "unites": None},
            ]
        }
    }
    rows = mapper.map_prix_extraits_rows(ticket, "tid")

    assert len(rows) == 1
    assert rows[0]["raw_text"] == "OK"
    assert rows[0]["unit_price"] == 0.0
    assert rows[0]["quantity"] == 1.0
