"""Auth Firebase via ADC — verification des JWT Bearer.

initialize_app() sans arg -> ADC (backend-sa en prod, adc login en local).
Pas de cle JSON (org policy iam.disableServiceAccountKeyCreation) ; verif du JWT
contre les certs publics Google, aucun role IAM Firebase requis sur la SA.
PRT_AUTH_DISABLE=1 (dev only) renvoie un user fake ; jamais en prod.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import firebase_admin
from fastapi import Header, HTTPException, status
from firebase_admin import auth as firebase_auth

from .config import Settings, get_settings
from .logging import get_logger

logger = get_logger(__name__)

_firebase_initialized = False


@dataclass
class AuthenticatedUser:
    # uid = users.firebase_uid cote Cloud SQL
    uid: str
    email: str | None
    email_verified: bool


def _ensure_firebase_initialized() -> None:
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        firebase_admin.initialize_app()
    except ValueError:
        # deja init (testcontainers / reload uvicorn)
        pass
    _firebase_initialized = True


def _bypass_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        uid="dev-bypass",
        email="dev-bypass@local.test",
        email_verified=True,
    )


async def verify_bearer(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    # 401 token manquant/invalide/expire ; bypass si PRT_AUTH_DISABLE et env != prod
    settings = get_settings()
    if settings.prt_auth_disable:
        if settings.prt_env == "prod":
            # jamais de bypass en prod
            logger.error("auth_disable_in_prod_forbidden")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Auth bypass not allowed in prod.",
            )
        logger.warning("auth_bypassed_dev_only")
        return _bypass_user()

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _ensure_firebase_initialized()
    try:
        # check_revoked=False : evite un appel HTTP par requete ; on couvre via
        # l'expiration courte des tokens (1h)
        payload = await asyncio.to_thread(firebase_auth.verify_id_token, token, None, False)
    except firebase_auth.ExpiredIdTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (firebase_auth.InvalidIdTokenError, ValueError) as exc:
        # ValueError = token mal forme ; log serveur only, pas de leak client
        logger.info("auth_invalid_token", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return AuthenticatedUser(
        uid=payload["uid"],
        email=payload.get("email"),
        email_verified=bool(payload.get("email_verified", False)),
    )


def reset_for_tests(settings: Settings | None = None) -> None:
    global _firebase_initialized
    _firebase_initialized = False
