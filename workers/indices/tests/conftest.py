"""Isolation env, OIDC bypass, project fixture."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("PRT_") or key in {"GOOGLE_CLOUD_PROJECT"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRT_OIDC_DISABLE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "price-tracker-test")
