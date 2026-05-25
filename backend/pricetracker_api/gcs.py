"""Signed URLs V4 PUT pour l'upload de tickets, SANS clé JSON.

Org policy `iam.disableServiceAccountKeyCreation` interdit la création de
clés JSON pour les SAs. `Blob.generate_signed_url()` du SDK GCS exige par
défaut une clé pour signer ; le contournement officiel est de déléguer la
signature à l'API IAM Credentials (`signBlob`) en passant :
  - `service_account_email` : la SA qui signe (la backend-sa elle-même)
  - `access_token` : l'access token courant de l'ADC

Le SA doit avoir `roles/iam.serviceAccountTokenCreator` sur lui-même.
Cette binding est ajoutée par `infra/envs/prod/iam_backend.tf`.

Référence : https://cloud.google.com/storage/docs/access-control/signed-urls#impersonation
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
    """Génère une Signed URL V4 PUT pour `tickets/raw/{user_id}/{uuid}.jpg`.

    Le `content_type` est fixé dans la signature : le client DOIT envoyer
    exactement le même `Content-Type` dans son PUT, sinon GCS refuse (403).
    On contraint à `image/jpeg` ou `image/png` pour éviter d'archiver autre
    chose (PDF, ZIP) — validation côté serveur.

    Retourne aussi le `gcs_path` (gs://...) pour le persister dans la table
    `tickets.gcs_path`.
    """
    if content_type not in {"image/jpeg", "image/png"}:
        raise ValueError(f"Unsupported content_type: {content_type!r}")

    settings = get_settings()
    if not settings.prt_gcs_bucket_bronze:
        raise RuntimeError("PRT_GCS_BUCKET_BRONZE not configured.")

    # ADC refresh — indispensable pour récupérer un access_token valide à
    # passer à `generate_signed_url`. Sans ce refresh, `credentials.token`
    # est `None` côté Cloud Run au premier appel.
    credentials, _project = adc_default()
    credentials.refresh(GoogleAuthRequest())

    # `service_account_email` n'est pas dispo sur toutes les classes
    # `Credentials` (ex: UserCredentials en local). Fallback explicite.
    sa_email = getattr(credentials, "service_account_email", None)
    if not sa_email:
        raise RuntimeError(
            "ADC credentials do not expose service_account_email. "
            "Run with a service account (Cloud Run) or impersonate one locally."
        )

    object_uuid = ticket_uuid or uuid.uuid4().hex
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
