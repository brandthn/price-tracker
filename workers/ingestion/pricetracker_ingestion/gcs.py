
from __future__ import annotations

from datetime import date

from google.cloud import storage

from .logging import get_logger

logger = get_logger(__name__)


def upload_snapshot(
    *,
    project_id: str,
    bucket: str,
    snapshot_date: date,
    local_path: str,
    prefix: str = "open-prices",
) -> str:
    object_name = f"{prefix}/dt={snapshot_date.isoformat()}/snapshot.parquet"
    client = storage.Client(project=project_id)
    blob = client.bucket(bucket).blob(object_name)

    blob.upload_from_filename(local_path, content_type="application/octet-stream")
    uri = f"gs://{bucket}/{object_name}"
    logger.info(
        "gcs_upload_done",
        bucket=bucket,
        object=object_name,
        uri=uri,
        size_bytes=blob.size,
    )
    return uri
