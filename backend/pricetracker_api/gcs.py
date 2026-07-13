"""Signed URLs V4 pour tickets, sans cle JSON.

org policy iam.disableServiceAccountKeyCreation -> pas de cle pour signer. On
delegue la signature a IAM Credentials (signBlob) via service_account_email +
access_token ADC. La SA a besoin de roles/iam.serviceAccountTokenCreator sur
elle-meme (iam_backend.tf).
https://cloud.google.com/storage/docs/access-control/signed-urls#impersonation
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from functools import lru_cache

from google.auth import default as adc_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import storage

from .config import get_settings
from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class TicketUploadURL:
    upload_url: str
    gcs_path: str  # gs:// path (sans https)
    object_name: str  # path relatif dans le bucket
    expires_at: datetime.datetime
    content_type: str


@lru_cache(maxsize=1)
def _storage_client() -> storage.Client:
    settings = get_settings()
    project = settings.google_cloud_project or None
    return storage.Client(project=project)


def reset_for_tests() -> None:
    _storage_client.cache_clear()


def generate_ticket_upload_url(
    *,
    user_id: str,
    content_type: str = "image/jpeg",
    ticket_uuid: str | None = None,
) -> TicketUploadURL:
    # content_type fige dans la signature : le PUT client doit envoyer le meme,
    # sinon 403. Restreint a jpeg/png pour ne pas archiver n'importe quoi.
    if content_type not in {"image/jpeg", "image/png"}:
        raise ValueError(f"Unsupported content_type: {content_type!r}")

    settings = get_settings()
    if not settings.prt_gcs_bucket_bronze:
        raise RuntimeError("PRT_GCS_BUCKET_BRONZE not configured.")

    # refresh sinon credentials.token est None au 1er appel Cloud Run
    credentials, _project = adc_default()
    credentials.refresh(GoogleAuthRequest())

    # service_account_email absent sur certaines Credentials (UserCredentials local)
    sa_email = getattr(credentials, "service_account_email", None)
    if not sa_email:
        raise RuntimeError(
            "ADC credentials do not expose service_account_email. "
            "Run with a service account (Cloud Run) or impersonate one locally."
        )

    object_uuid = ticket_uuid or str(uuid.uuid4())
    object_name = f"tickets/raw/{user_id}/{object_uuid}.jpg"

    bucket = _storage_client().bucket(settings.prt_gcs_bucket_bronze)
    blob = bucket.blob(object_name)

    ttl_min = settings.prt_signed_url_ttl_min
    expiration = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=ttl_min)

    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=ttl_min),
        method="PUT",
        content_type=content_type,
        service_account_email=sa_email,
        access_token=credentials.token,
    )

    gcs_path = f"gs://{settings.prt_gcs_bucket_bronze}/{object_name}"
    logger.info(
        "signed_url_generated",
        user_id=user_id,
        object_name=object_name,
        ttl_min=ttl_min,
    )
    return TicketUploadURL(
        upload_url=upload_url,
        gcs_path=gcs_path,
        object_name=object_name,
        expires_at=expiration,
        content_type=content_type,
    )


@dataclass
class TicketReadURL:
    read_url: str
    expires_at: datetime.datetime


def _object_name_from_gcs_path(gcs_path: str) -> str:
    settings = get_settings()
    prefix = f"gs://{settings.prt_gcs_bucket_bronze}/"
    if not gcs_path.startswith(prefix):
        raise ValueError(f"gcs_path outside bronze bucket: {gcs_path!r}")
    return gcs_path[len(prefix) :]


def generate_ticket_read_url(*, gcs_path: str) -> TicketReadURL:
    # meme impersonation signBlob que l'upload. l'appelant doit deja avoir
    # verifie que le ticket appartient a l'utilisateur.
    settings = get_settings()
    if not settings.prt_gcs_bucket_bronze:
        raise RuntimeError("PRT_GCS_BUCKET_BRONZE not configured.")

    credentials, _project = adc_default()
    credentials.refresh(GoogleAuthRequest())
    sa_email = getattr(credentials, "service_account_email", None)
    if not sa_email:
        raise RuntimeError(
            "ADC credentials do not expose service_account_email. "
            "Run with a service account (Cloud Run) or impersonate one locally."
        )

    object_name = _object_name_from_gcs_path(gcs_path)
    bucket = _storage_client().bucket(settings.prt_gcs_bucket_bronze)
    blob = bucket.blob(object_name)

    ttl_min = settings.prt_signed_url_ttl_min
    expiration = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=ttl_min)

    read_url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=ttl_min),
        method="GET",
        service_account_email=sa_email,
        access_token=credentials.token,
    )

    logger.info("signed_read_url_generated", object_name=object_name, ttl_min=ttl_min)
    return TicketReadURL(read_url=read_url, expires_at=expiration)
