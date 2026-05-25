"""Parse Pub/Sub push envelopes (GCS object notifications)."""

from __future__ import annotations

import base64
import json
import re
from pathlib import PurePosixPath

_TICKET_PATH_RE = re.compile(
    r"^tickets/raw/[^/]+/([0-9a-fA-F-]{36})\.[a-zA-Z0-9]+$",
)


def parse_pubsub_envelope(body: bytes) -> tuple[str, str]:
    """Decode Pub/Sub push body and return ``(gcs_bucket, gcs_object_path)``."""
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
        storage_object = json.loads(inner_raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Pub/Sub message.data is not valid base64 JSON.") from exc

    if not isinstance(storage_object, dict):
        raise ValueError("Decoded storage object must be a JSON object.")

    bucket = storage_object.get("bucket")
    name = storage_object.get("name")
    if not bucket or not name:
        raise ValueError("Storage object missing 'bucket' or 'name'.")

    return str(bucket), str(name)


def extract_ticket_id(gcs_object_path: str) -> str:
    """Return ticket UUID from ``tickets/raw/{user_id}/{uuid}.ext``."""
    normalized = PurePosixPath(gcs_object_path).as_posix()
    match = _TICKET_PATH_RE.match(normalized)
    if not match:
        raise ValueError(
            f"GCS object path does not match tickets/raw/{{user_id}}/{{uuid}}.ext: "
            f"{gcs_object_path!r}"
        )
    return match.group(1).lower()


def extract_user_id(gcs_object_path: str) -> str:
    """Return user_id segment from ``tickets/raw/{user_id}/{uuid}.ext``."""
    parts = PurePosixPath(gcs_object_path).parts
    if len(parts) < 4 or parts[0] != "tickets" or parts[1] != "raw":
        raise ValueError(f"Cannot extract user_id from path: {gcs_object_path!r}")
    return parts[2]
