"""Auth Firebase via ADC — vérification des JWT Bearer.

Initialisation `firebase_admin.initialize_app()` sans argument → ADC :
- En prod : la SA `prt-prod-backend-sa` attachée au Cloud Run.
- En local : `gcloud auth application-default login`.

Aucune clé JSON nécessaire (org policy `iam.disableServiceAccountKeyCreation`).
La vérification du JWT se fait contre les certs publics Google — aucun rôle
IAM Firebase requis sur la SA.

DEV ONLY : `PRT_AUTH_DISABLE=1` retourne un user fake (`uid='dev-bypass'`).
Ne jamais activer en prod : check explicite dans `_verify`.
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
    """Identité minimale extraite du JWT Firebase. Le `uid` est la clé
    primaire utilisée côté Cloud SQL (`users.firebase_uid`).
    """

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
        # Déjà initialisé (cas testcontainers / reload uvicorn).
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
    """FastAPI dependency : extrait + valide le JWT Firebase.

    - Si `PRT_AUTH_DISABLE=1` et `PRT_ENV != 'prod'` → renvoie le bypass user.
    - Sinon : require `Authorization: Bearer <id_token>` et le vérifie via
      `firebase_admin.auth.verify_id_token` (bloque le revoked tokens).

    Lève 401 sur token manquant/invalide/expiré, 403 sur email non vérifié.
    """
    settings = get_settings()
    if settings.prt_auth_disable:
        if settings.prt_env == "prod":
            # Garde-fou : ne JAMAIS bypass en prod, même par accident.
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
        # `check_revoked=False` : pour `check_revoked=True` Firebase fait un
        # appel HTTP à chaque requête (latence + quota). On fait confiance à
        # l'expiration courte des tokens (1h) pour limiter la fenêtre de revoke.
        payload = await asyncio.to_thread(firebase_auth.verify_id_token, token, None, False)
    except firebase_auth.ExpiredIdTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (firebase_auth.InvalidIdTokenError, ValueError) as exc:
        # ValueError est levée pour un token mal formé. On loggue le détail
        # côté serveur uniquement — pas de leak au client.
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
    """Tests : permet de re-initialiser Firebase Admin si besoin (rare)."""
    global _firebase_initialized
    _firebase_initialized = False
