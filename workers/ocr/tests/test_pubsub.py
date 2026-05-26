"""Unit tests for Pub/Sub envelope parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pricetracker_ocr import pubsub

FIXTURE = Path(__file__).parent / "fixtures" / "pubsub_envelope.json"


def test_parse_pubsub_envelope_happy_path():
    body = FIXTURE.read_bytes()
    bucket, path = pubsub.parse_pubsub_envelope(body)
    assert bucket == "price-tracker-test-bronze"
    assert path == "tickets/raw/user-abc-123/550e8400-e29b-41d4-a716-446655440000.jpg"


def test_parse_pubsub_envelope_missing_data():
    body = json.dumps({"message": {}}).encode()
    with pytest.raises(ValueError, match="missing 'data'"):
        pubsub.parse_pubsub_envelope(body)


def test_extract_ticket_id_valid():
    path = "tickets/raw/user-abc-123/550e8400-e29b-41d4-a716-446655440000.jpg"
    assert pubsub.extract_ticket_id(path) == "550e8400-e29b-41d4-a716-446655440000"


def test_extract_ticket_id_hex_no_hyphens():
    """Legacy backend bug: ticket_id.hex produces 32-char no-hyphen string."""
    path = "tickets/raw/user-abc-123/550e8400e29b41d4a716446655440000.jpg"
    assert pubsub.extract_ticket_id(path) == "550e8400-e29b-41d4-a716-446655440000"


def test_extract_ticket_id_malformed():
    with pytest.raises(ValueError):
        pubsub.extract_ticket_id("wrong/path/file.jpg")
