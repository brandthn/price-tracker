"""Tests auth : bypass DEV, refus en prod, JWT invalide → 401."""

from __future__ import annotations

import pytest

from pricetracker_api import auth
from pricetracker_api.auth import AuthenticatedUser, verify_bearer


@pytest.mark.asyncio
async def test_bypass_returns_dev_user_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRT_AUTH_DISABLE", "1")
    monkeypatch.setenv("PRT_ENV", "dev")
    from pricetracker_api import config

    config.reset_settings_cache()

    user = await verify_bearer(authorization=None)
    assert isinstance(user, AuthenticatedUser)
    assert user.uid == "dev-bypass"
    assert user.email_verified is True


@pytest.mark.asyncio
async def test_bypass_forbidden_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRT_AUTH_DISABLE", "1")
    monkeypatch.setenv("PRT_ENV", "prod")
    from pricetracker_api import config

    config.reset_settings_cache()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await verify_bearer(authorization=None)
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_missing_bearer_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRT_AUTH_DISABLE", "0")
    from pricetracker_api import config

    config.reset_settings_cache()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await verify_bearer(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_jwt_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRT_AUTH_DISABLE", "0")
    from pricetracker_api import config

    config.reset_settings_cache()

    # Mock firebase_admin.auth.verify_id_token pour qu'il lève InvalidIdTokenError.
    from firebase_admin import auth as fa_auth

    def _raise(*_a, **_k):
        raise fa_auth.InvalidIdTokenError("bad")

    monkeypatch.setattr(fa_auth, "verify_id_token", _raise)
    monkeypatch.setattr(auth, "_firebase_initialized", True)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await verify_bearer(authorization="Bearer not-a-real-jwt")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_valid_jwt_returns_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRT_AUTH_DISABLE", "0")
    from pricetracker_api import config

    config.reset_settings_cache()

    from firebase_admin import auth as fa_auth

    def _ok(*_a, **_k):
        return {"uid": "user-123", "email": "alice@example.com", "email_verified": True}

    monkeypatch.setattr(fa_auth, "verify_id_token", _ok)
    monkeypatch.setattr(auth, "_firebase_initialized", True)

    user = await verify_bearer(authorization="Bearer xyz")
    assert user.uid == "user-123"
    assert user.email == "alice@example.com"
