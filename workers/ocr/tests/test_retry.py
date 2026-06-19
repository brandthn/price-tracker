"""Tests du re-OCR tier-2 (boucle de feedback 👎) : envelope, prompt, mapping."""

from __future__ import annotations

import base64
import json

import pytest

from pricetracker_ocr import gcs, mapper, pubsub, retry_ocr


def _retry_envelope(ticket_id: str) -> bytes:
    inner = json.dumps({"ticket_id": ticket_id}).encode()
    return json.dumps({"message": {"data": base64.b64encode(inner).decode()}}).encode()


def test_parse_retry_envelope_happy_path() -> None:
    body = _retry_envelope("550e8400-e29b-41d4-a716-446655440000")
    assert pubsub.parse_retry_envelope(body) == "550e8400-e29b-41d4-a716-446655440000"


def test_parse_retry_envelope_missing_ticket_id() -> None:
    inner = base64.b64encode(json.dumps({"foo": "bar"}).encode()).decode()
    body = json.dumps({"message": {"data": inner}}).encode()
    with pytest.raises(ValueError, match="ticket_id"):
        pubsub.parse_retry_envelope(body)


def test_split_gs_uri() -> None:
    bucket, obj = gcs.split_gs_uri(
        "gs://price-tracker-prod-01-bronze/tickets/raw/u/abc.jpg"
    )
    assert bucket == "price-tracker-prod-01-bronze"
    assert obj == "tickets/raw/u/abc.jpg"


def test_split_gs_uri_malformed() -> None:
    with pytest.raises(ValueError):
        gcs.split_gs_uri("https://example.com/x.jpg")


def test_build_previous_extraction_json() -> None:
    prev_rows = [
        {"raw_text": "PAIN", "unit_price": 1.2, "quantity": 2},
        {"raw_text": "LAIT", "unit_price": 0.99, "quantity": None},
    ]
    out = retry_ocr.build_previous_extraction_json("CARREFOUR", "2024-03-15", prev_rows)
    parsed = json.loads(out)
    assert parsed["ticket"]["chaine_supermarche"] == "CARREFOUR"
    assert len(parsed["ticket"]["produits"]) == 2
    assert parsed["ticket"]["produits"][0]["nom_produit"] == "PAIN"
    # quantity NULL → 1 par défaut
    assert parsed["ticket"]["produits"][1]["unites"] == 1


def test_build_corrective_prompt_includes_previous() -> None:
    prev = '{"ticket": {"produits": []}}'
    prompt = retry_ocr.build_corrective_prompt(prev)
    assert prev in prompt
    assert "ERRONÉE" in prompt
    # Garde le schéma de base receipt_ocr.
    assert "nom_produit" in prompt


def test_run_retry_ocr_parses_and_sets_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _FakeProvider:
        def __init__(self, model: str | None = None) -> None:
            captured["model"] = model

        def analyze(self, _path: str, prompt: str) -> str:
            captured["prompt"] = prompt
            return json.dumps(
                {"ticket": {"chaine_supermarche": "X", "produits": [
                    {"nom_produit": "TOMATES", "prix_unitaire_ou_kg": 2.5, "unites": 1}
                ]}}
            )

    monkeypatch.setattr(retry_ocr, "GroqProvider", _FakeProvider)

    result = retry_ocr.run_retry_ocr(
        b"\xff\xd8fakejpeg", '{"ticket": {"produits": []}}', "my-tier2-model"
    )

    assert result["ticket"]["produits"][0]["nom_produit"] == "TOMATES"
    assert captured["model"] == "my-tier2-model"
    # Le mapping en aval reste identique au tier-1.
    rows = mapper.map_prix_extraits_rows(result, "ticket-123")
    assert rows[0]["raw_text"] == "TOMATES"
    assert rows[0]["needs_validation"] is True


def test_run_retry_ocr_repairs_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProvider:
        def __init__(self, model: str | None = None) -> None:
            pass

        def analyze(self, _path: str, _prompt: str) -> str:
            # JSON tronqué / réparable par json_repair.
            return '{"ticket": {"chaine_supermarche": "X", "produits": ['

    monkeypatch.setattr(retry_ocr, "GroqProvider", _FakeProvider)

    result = retry_ocr.run_retry_ocr(b"img", "{}", "m")
    assert isinstance(result, dict)
    assert "ticket" in result
