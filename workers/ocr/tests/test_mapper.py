"""Unit tests for receipt_ocr → SQL mapping."""

from __future__ import annotations

from datetime import date

from pricetracker_ocr import mapper


def test_map_ticket_fields_enseigne(sample_ocr_result):
    fields = mapper.map_ticket_fields(
        sample_ocr_result,
        "550e8400-e29b-41d4-a716-446655440000",
        "tickets/raw/u/t.jpg",
        "groq",
        100,
        1.0,
    )
    assert fields["enseigne"] == "CARREFOUR MARKET"


def test_map_ticket_fields_parses_date(sample_ocr_result):
    fields = mapper.map_ticket_fields(
        sample_ocr_result,
        "550e8400-e29b-41d4-a716-446655440000",
        "tickets/raw/u/t.jpg",
        "groq",
        100,
        1.0,
    )
    assert fields["ticket_date"] == date(2024, 3, 15)


def test_map_ticket_fields_empty_date():
    ocr = {"ticket": {"date": "", "chaine_supermarche": "X", "produits": []}}
    fields = mapper.map_ticket_fields(ocr, "id", "path", "groq", 1, 1.0)
    assert fields["ticket_date"] is None


def test_map_prix_extraits_ean_and_validation(sample_ocr_result):
    rows = mapper.map_prix_extraits_rows(
        sample_ocr_result, "550e8400-e29b-41d4-a716-446655440000"
    )
    assert len(rows) == 2
    for row in rows:
        assert row["ean"] is None
        assert row["match_method"] == "none"
        assert row["match_confidence"] is None
        assert row["needs_validation"] is True
        assert row["validated_by_user"] is False


def test_map_prix_extraits_line_index_and_totals(sample_ocr_result):
    rows = mapper.map_prix_extraits_rows(
        sample_ocr_result, "550e8400-e29b-41d4-a716-446655440000"
    )
    assert rows[0]["line_index"] == 0
    assert rows[1]["line_index"] == 1
    assert rows[0]["line_total"] == 2.4
    assert rows[0]["unit_price"] == 1.2
    assert rows[0]["quantity"] == 2.0
