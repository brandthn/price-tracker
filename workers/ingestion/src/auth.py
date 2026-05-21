"""Vérification OIDC pour `/run`.

Le caller (Cloud Scheduler) attache un Bearer JWT signé par Google. Le worker
doit valider :
- signature contre les JWKs publics Google,
- `aud` == URL exacte du service Cloud Run,
- `iss` ∈ issuers Google connus,
- `email` ∈ liste blanche (worker-sa) si la liste est non vide,
- `email_verified` true.

Cloud Run vérifie déjà la signature côté ingress quand `allow_unauthenticated=false`,
mais on double-check `aud` et `email` côté applicatif pour ne pas reposer
uniquement sur la couche infra (defense in depth).
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .config import Settings, get_settings
from .logging import get_logger

logger = get_logger(__name__)

_request_transport = google_requests.Request()


def _resolve_audience(settings: Settings, request: Request) -> str:
    if settings.prt_oidc_required_audience:
        return settings.prt_oidc_required_audience
    # Fallback : reconstruire l'URL telle que Cloud Run la voit.
    # Cloud Scheduler signe l'audience = URL du service (sans path).
    forwarded_host = request.headers.get("x-forwarded-host") or request.url.hostname
    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
    return f"{forwarded_proto}://{forwarded_host}"


def verify_oidc(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """FastAPI dependency. Renvoie le payload décodé en cas de succès."""
    settings = get_settings()
    if settings.prt_oidc_disable:
        logger.warning("oidc_check_disabled", reason="PRT_OIDC_DISABLE=1 (dev only)")
        return {"email": "dev-bypass", "sub": "dev"}

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token.",
        )
    token = authorization.split(" ", 1)[1].strip()

    audience = _resolve_audience(settings, request)
    try:
        payload = id_token.verify_oauth2_token(token, _request_transport, audience=audience)
    except ValueError as exc:
        logger.warning("oidc_verify_failed", error=str(exc), audience=audience)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OIDC token.",
        ) from exc

    if payload.get("iss") not in settings.allowed_issuers:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Issuer {payload.get('iss')!r} not allowed.",
        )

    if not payload.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Caller email not verified.",
        )

    allowlist = settings.allowed_service_accounts
    if allowlist and payload.get("email") not in allowlist:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Caller {payload.get('email')!r} not in allowlist.",
        )

    return payload
