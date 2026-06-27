"""Tests worker OCR tier-2 : envelope, gs uri, prompt correctif, OCR, mapping."""

from __future__ import annotations

import base64
import json

import pytest

from pricetracker_ocr_llm import gcs, mapper, ocr, pubsub
from pricetracker_ocr_llm.config import Settings


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
    bucket, obj = gcs.split_gs_uri("gs://price-tracker-prod-01-bronze/tickets/raw/u/abc.jpg")
    assert bucket == "price-tracker-prod-01-bronze"
    assert obj == "tickets/raw/u/abc.jpg"


def test_split_gs_uri_malformed() -> None:
    with pytest.raises(ValueError):
        gcs.split_gs_uri("https://example.com/x.jpg")


def test_default_model_is_proven() -> None:
    # Défaut sûr (même modèle que le tier-1) pour la fiabilité démo.
    assert Settings().prt_ocr_model == "meta-llama/llama-4-scout-17b-16e-instruct"


def test_build_previous_extraction_json() -> None:
    prev_rows = [
        {"raw_text": "PAIN", "unit_price": 1.2, "quantity": 2},
        {"raw_text": "LAIT", "unit_price": 0.99, "quantity": None},
    ]
    out = ocr.build_previous_extraction_json("CARREFOUR", "2024-03-15", prev_rows)
    parsed = json.loads(out)
    assert parsed["ticket"]["chaine_supermarche"] == "CARREFOUR"
    assert parsed["ticket"]["produits"][0]["nom_produit"] == "PAIN"
    assert parsed["ticket"]["produits"][1]["unites"] == 1


def test_build_prompt_with_and_without_previous() -> None:
    prev = '{"ticket": {"produits": []}}'
    with_prev = ocr.build_prompt(prev)
    assert prev in with_prev and "ERRONÉE" in with_prev
    plain = ocr.build_prompt(None)
    assert "ERRONÉE" not in plain
    assert "nom_produit" in plain  # garde le schéma de base


def test_run_ocr_parses_and_maps(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(ocr, "GroqProvider", _FakeProvider)

    result = ocr.run_ocr(b"\xff\xd8img", "my-model", '{"ticket": {"produits": []}}')

    assert result["ticket"]["produits"][0]["nom_produit"] == "TOMATES"
    assert captured["model"] == "my-model"
    assert "ERRONÉE" in captured["prompt"]
    rows = mapper.map_prix_extraits_rows(result, "t-1")
    assert rows[0]["raw_text"] == "TOMATES"
    assert rows[0]["needs_validation"] is True


def test_run_ocr_repairs_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProvider:
        def __init__(self, model: str | None = None) -> None:
            pass

        def analyze(self, _path: str, _prompt: str) -> str:
            return '{"ticket": {"chaine_supermarche": "X", "produits": ['

    monkeypatch.setattr(ocr, "GroqProvider", _FakeProvider)
    result = ocr.run_ocr(b"img", "m", None)
    assert isinstance(result, dict) and "ticket" in result
