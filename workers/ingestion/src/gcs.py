"""Upload du snapshot transformé vers GCS Bronze.

Path : `gs://<bronze>/open-prices/dt=YYYY-MM-DD/snapshot.parquet`
- partitionnement Hive-style (lisible par BQ external table ou Dataproc)
- versioning bucket = ON → re-runs du même jour écrasent l'objet courant
  tout en gardant la version précédente pour la fenêtre de rétention
  (90j NEARLINE).
"""

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
    # `if_generation_match=None` → upload normal, versioning bucket gère
    # l'historique. Pas d'optimistic concurrency ici (un seul writer cron).
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
