"""Fixtures pytest — env isole + mocks Firebase/BQ/GCS + override DB.

Pas de testcontainers/Docker en CI : on mocke get_session pour les routers DB.
Les tests SQL reels passent par le proxy Cloud SQL local, hors CI.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # reset PRT_*/GCP + bypass auth pour tester les endpoints sans forger de JWT
    for key in list(os.environ.keys()):
        if key.startswith("PRT_") or key in {"GOOGLE_CLOUD_PROJECT"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "price-tracker-test")
    monkeypatch.setenv("PRT_ENV", "dev")
    monkeypatch.setenv("PRT_AUTH_DISABLE", "1")
    monkeypatch.setenv("PRT_GCS_BUCKET_BRONZE", "price-tracker-test-bronze")
    monkeypatch.setenv("PRT_PG_PASSWORD", "test-password")

    from pricetracker_api import bq, config, gcs

    config.reset_settings_cache()
    bq.reset_client_cache()
    gcs.reset_for_tests()


@pytest.fixture
def fake_session() -> MagicMock:
    # MagicMock d'AsyncSession, methodes async configurables test par test
    session = MagicMock()

    async def _async_noop(*_args, **_kwargs):
        return None

    async def _async_iter() -> AsyncIterator[MagicMock]:
        yield session

    session.commit = _async_noop
    session.refresh = _async_noop
    session.rollback = _async_noop
    return session
