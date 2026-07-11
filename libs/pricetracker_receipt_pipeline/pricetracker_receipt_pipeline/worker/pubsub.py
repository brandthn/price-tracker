"""Parse les enveloppes Pub/Sub push des workers OCR → ``ticket_id``.

Un même worker peut être déclenché de deux façons, avec deux formats de payload :
  - **tier-1** : notification GCS du bucket bronze (topic ``ticket-uploaded``),
    payload = objet storage ``{"bucket", "name": "tickets/raw/.../{uuid}.ext"}``.
  - **tier-2/3** : escalade publiée par le backend (topics ``ocr-vlm-*`` /
    ``ocr-retry``), payload = ``{"ticket_id": "..."}``.
En aval le worker relit ``gcs_path`` en DB par ``ticket_id`` : les deux chemins
convergent donc dès qu'on a extrait le ``ticket_id``.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import PurePosixPath

# tickets/raw/{user_id}/{uuid}.ext — accepte l'UUID canonique (36 car.) ou
# l'hex sans tirets (32 car., ancien bug backend).
_TICKET_PATH_RE = re.compile(
    r"^tickets/raw/[^/]+/([0-9a-fA-F]{32}|[0-9a-fA-F-]{36})\.[a-zA-Z0-9]+$",
)


def _ticket_id_from_gcs_name(name: str) -> str:
    """``tickets/raw/{user_id}/{uuid}.ext`` → UUID normalisé."""
    match = _TICKET_PATH_RE.match(PurePosixPath(name).as_posix())
    if not match:
        raise ValueError(f"GCS object name is not a ticket path: {name!r}")
    raw = match.group(1).lower()
    if len(raw) == 32:
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return raw


def parse_push_envelope(body: bytes) -> str:
    """Decode le push body → ``ticket_id`` (format escalade OU notification GCS)."""
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

    # Escalade backend : ticket_id explicite.
    ticket_id = payload.get("ticket_id")
    if isinstance(ticket_id, str) and ticket_id:
        return ticket_id

    # Notification GCS : dériver le ticket_id du chemin de l'objet.
    name = payload.get("name")
    if isinstance(name, str) and name:
        return _ticket_id_from_gcs_name(name)

    raise ValueError("Push payload has neither 'ticket_id' nor a GCS 'name'.")
