"""Pytest fixtures — env isolation and settings cache reset."""

from __future__ import annotations

import os

import pytest

from pricetracker_ocr_paddle.config import get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith(("PRT_", "RECEIPT_")) or key == "GOOGLE_CLOUD_PROJECT":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRT_OIDC_DISABLE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "price-tracker-test")
    monkeypatch.setenv("PRT_PG_HOST", "localhost")
    monkeypatch.setenv("PRT_PG_PASSWORD", "test")
    get_settings.cache_clear()
