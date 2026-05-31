"""Fixtures pytest — env isolé + mocks Firebase/BQ/GCS + override DB.

Stratégie testcontainers vs SQLite vs mocks :
- Phase 7 V1 : on n'embarque pas testcontainers/Docker dans la CI (lourd).
  À la place, on mocke `get_session` pour les routers qui touchent la DB.
- Les tests qui exercent vraiment le SQL passent par le mode local (proxy
  Cloud SQL) au choix du dev, hors CI.
- Phase 11 : ajouter testcontainers + tests d'intégration plus poussés.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset env vars PRT_* + GCP avant chaque test. Active le bypass d'auth
    par défaut pour faciliter les tests des endpoints authentifiés sans
    avoir à forger un JWT Firebase.
    """
    for key in list(os.environ.keys()):
        if key.startswith("PRT_") or key in {"GOOGLE_CLOUD_PROJECT"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "price-tracker-test")
    monkeypatch.setenv("PRT_ENV", "dev")
    monkeypatch.setenv("PRT_AUTH_DISABLE", "1")
    monkeypatch.setenv("PRT_GCS_BUCKET_BRONZE", "price-tracker-test-bronze")
    monkeypatch.setenv("PRT_PG_PASSWORD", "test-password")

    # Reset les caches lru_cache des modules de config / clients.
    from pricetracker_api import bq, config, gcs

    config.reset_settings_cache()
    bq.reset_client_cache()
    gcs.reset_for_tests()


@pytest.fixture
def fake_session() -> MagicMock:
    """Mock de la session SQLAlchemy AsyncSession.

    On retourne un MagicMock avec les méthodes async (add/commit/refresh/...)
    setattr-able pour les configurer test par test.
    """
    session = MagicMock()

    async def _async_noop(*_args, **_kwargs):
        return None

    async def _async_iter() -> AsyncIterator[MagicMock]:
        yield session

    session.commit = _async_noop
    session.refresh = _async_noop
    session.rollback = _async_noop
    return session
