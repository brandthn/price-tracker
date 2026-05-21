"""Isolation des tests vis-à-vis de l'environnement Cloud Run.

On purge / override les env vars `PRT_*`, `HF_TOKEN`, `GOOGLE_CLOUD_PROJECT`
pour éviter qu'un `gcloud auth application-default login` local fasse
fuiter du contexte dans les tests.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("PRT_") or key in {"HF_TOKEN", "GOOGLE_CLOUD_PROJECT"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRT_OIDC_DISABLE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "price-tracker-test")
