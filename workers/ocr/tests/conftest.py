"""Pytest fixtures — env isolation and settings cache reset."""

from __future__ import annotations

import os

import pytest

from pricetracker_ocr.config import get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("PRT_") or key in {"GOOGLE_CLOUD_PROJECT", "GROQ_API_KEY", "groq_key"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRT_OIDC_DISABLE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "price-tracker-test")
    monkeypatch.setenv("PRT_BRONZE_BUCKET", "price-tracker-test-bronze")
    monkeypatch.setenv("PRT_PG_HOST", "localhost")
    monkeypatch.setenv("PRT_PG_PASSWORD", "test")
    get_settings.cache_clear()


@pytest.fixture
def sample_ocr_result() -> dict:
    return {
        "ticket": {
            "date": "20240315 14:30",
            "chaine_supermarche": "CARREFOUR MARKET",
            "adresse": "1 rue Example, 75001 Paris",
            "produits": [
                {
                    "nom_produit": "PAIN COMPLET",
                    "prix_unitaire_ou_kg": 1.2,
                    "unites": 2,
                },
                {
                    "nom_produit": "LAIT UHT",
                    "prix_unitaire_ou_kg": 0.99,
                    "unites": 1,
                },
            ],
        }
    }
