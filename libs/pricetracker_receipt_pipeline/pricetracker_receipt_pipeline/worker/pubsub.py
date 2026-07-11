"""Parse les enveloppes Pub/Sub push des topics OCR par backend.

Le payload est notre propre JSON ``{"ticket_id": "..."}``, pas une
notification GCS. Copie de workers/ocr-llm/pricetracker_ocr_llm/pubsub.py
(``parse_retry_envelope`` renommé ``parse_push_envelope``).
"""

from __future__ import annotations

import base64
import json


def parse_push_envelope(body: bytes) -> str:
    """Decode le push body → ``ticket_id``."""
    try:
        outer = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Pub/Sub body is not valid JSON.") from exc

    message = outer.get("message")
    if not isinstance(message, dict):
        raise ValueError("Pub/Sub envelope missing 'message' object.")

    data_b64 = message.get("data")
    if not data_b64 or not isinstance(data_b64, str):
        raise ValueError("Pub/Sub message missing 'data' field.")

    try:
        inner_raw = base64.b64decode(data_b64, validate=True)
        payload = json.loads(inner_raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Pub/Sub message.data is not valid base64 JSON.") from exc

    if not isinstance(payload, dict):
        raise ValueError("Decoded push payload must be a JSON object.")

    ticket_id = payload.get("ticket_id")
    if not ticket_id or not isinstance(ticket_id, str):
        raise ValueError("Push payload missing 'ticket_id'.")
    return ticket_id
