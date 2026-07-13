

from __future__ import annotations

import json
from typing import Any

from google.cloud import storage

from .logging import get_logger

logger = get_logger(__name__)


def upload_report(
    *,
    bucket: str,
    prefix: str,
    run_date: str,
    payload: dict[str, Any],
) -> str:

    client = storage.Client()
    blob_path = f"{prefix}/date={run_date}/report.json"
    blob = client.bucket(bucket).blob(blob_path)
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    blob.upload_from_string(body, content_type="application/json")
    uri = f"gs://{bucket}/{blob_path}"
    logger.info("alerts_report_uploaded", uri=uri, bytes=len(body))
    return uri
