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


def test_parse_push_envelope_requires_ticket_id():
    with pytest.raises(ValueError, match="ticket_id"):
        parse_push_envelope(_envelope({"other": "x"}))
