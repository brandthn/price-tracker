"""Parse les enveloppes Pub/Sub push du topic `ocr-retry`.

Le payload est notre propre JSON ``{"ticket_id": "..."}`` (publié par le backend
sur 👎), pas une notification GCS.
"""

from __future__ import annotations

import base64
import json


def parse_retry_envelope(body: bytes) -> str:
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
        raise ValueError("Decoded retry payload must be a JSON object.")

    ticket_id = payload.get("ticket_id")
    if not ticket_id or not isinstance(ticket_id, str):
        raise ValueError("Retry payload missing 'ticket_id'.")
    return ticket_id
