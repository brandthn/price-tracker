"""Décodage de l'enveloppe Pub/Sub push."""

from __future__ import annotations

import base64
import json

import pytest

from pricetracker_receipt_pipeline.worker.pubsub import parse_push_envelope


def _envelope(payload: dict) -> bytes:
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return json.dumps({"message": {"data": data}, "subscription": "s"}).encode()


def test_parse_push_envelope_returns_ticket_id():
    assert parse_push_envelope(_envelope({"ticket_id": "abc"})) == "abc"


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        json.dumps({"subscription": "s"}).encode(),          # pas de 'message'
        json.dumps({"message": {}}).encode(),                # pas de 'data'
        json.dumps({"message": {"data": "!!!"}}).encode(),   # base64 invalide
    ],
)
def test_parse_push_envelope_rejects_malformed_bodies(body: bytes):
    with pytest.raises(ValueError):
        parse_push_envelope(body)


def test_parse_push_envelope_requires_ticket_id_or_gcs_name():
    with pytest.raises(ValueError, match="ticket_id"):
        parse_push_envelope(_envelope({"other": "x"}))


def test_parse_push_envelope_extracts_ticket_id_from_gcs_notification():
    # Notification GCS (tier-1) : le ticket_id vient du chemin de l'objet.
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    payload = {"bucket": "prt-prod-bronze", "name": f"tickets/raw/user-1/{uuid}.jpg"}
    assert parse_push_envelope(_envelope(payload)) == uuid


def test_parse_push_envelope_normalises_legacy_32hex_gcs_name():
    # Ancien format sans tirets → UUID canonique.
    payload = {"name": "tickets/raw/user-1/550e8400e29b41d4a716446655440000.png"}
    assert parse_push_envelope(_envelope(payload)) == "550e8400-e29b-41d4-a716-446655440000"


def test_parse_push_envelope_rejects_non_ticket_gcs_name():
    with pytest.raises(ValueError, match="ticket path"):
        parse_push_envelope(_envelope({"name": "some/other/object.jpg"}))
