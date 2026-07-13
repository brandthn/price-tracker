"""Tests GET /me/recommendations (reco substitut moins cher).

get_session override par une fausse session qui sert deux requetes : le SELECT User
de get_or_create_user et la requete reco, distinguees sur "product_substitutions".
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _reco_row(**overrides) -> dict:
    # row facon _RECOMMENDATIONS_SQL ; saving_pct en fraction (0-1) comme en base
    base = dict(
        source_ean="3017620422003",
        target_ean="3560070976478",
        tier=1,
        score=1.0,
        quantity_unit="kg",
        source_ppu=15.45,
        target_ppu=8.60,
        saving_per_unit=6.85,
        saving_pct=0.443,  # fraction, 44.3% en sortie
        packs_6m=6.0,      # 1 pack / mois
        source_name="Huile d'olive vierge extra",
        source_brand="Marque A",
        source_image_url="https://img/olive.jpg",
        target_name="Huile d'olive",
        target_brand="Marque B",
        target_image_url="https://img/olive2.jpg",
        # pack source 1 kg -> monthly_saving = 6.85 x 1 x (6/6)
        monthly_saving_eur=6.85,
    )
    base.update(overrides)
    return base


class _Mappings:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _Result:
    def __init__(self, *, scalar=None, rows: list[dict] | None = None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class _FakeSession:
    # user pour get_or_create_user, rows reco pour la requete SQL
    def __init__(self, user, reco_rows: list[dict]):
        self._user = user
        self._reco_rows = reco_rows
        self.last_params: dict | None = None
        self.last_sql: str | None = None

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "product_substitutions" in sql:
            self.last_sql = sql
            self.last_params = params
            return _Result(rows=self._reco_rows)
        return _Result(scalar=self._user)

    def add(self, *_a, **_k) -> None:  # pragma: no cover
        pass

    async def commit(self) -> None:  # pragma: no cover
        pass

    async def refresh(self, *_a, **_k) -> None:  # pragma: no cover
        pass


@pytest.fixture
def make_client():
    def _build(session: _FakeSession) -> TestClient:
        import importlib

        from pricetracker_api import main as main_mod
        from pricetracker_api.db import get_session

        importlib.reload(main_mod)
        main_mod.app.dependency_overrides[get_session] = lambda: session
        return TestClient(main_mod.app)

    return _build


def _fake_user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), firebase_uid="dev-bypass", email="dev@local.test")


def test_recommendations_happy_path(make_client) -> None:
    rows = [
        _reco_row(),
        _reco_row(
            source_ean="3229820129488",
            source_name="Café moulu",
            target_ean="3229820777771",
            target_name="Café moulu premier prix",
            tier=2,
            score=0.82,
            saving_per_unit=4.0,
            saving_pct=0.30,
            packs_6m=12.0,  # 2 packs / mois
            monthly_saving_eur=8.0,
        ),
    ]
    session = _FakeSession(_fake_user(), rows)
    client = make_client(session)

    r = client.get("/me/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["count"] == 2
    assert body["total_monthly_saving_eur"] == pytest.approx(14.85)

    first = body["items"][0]
    assert first["source"]["ean"] == "3017620422003"
    assert first["target"]["name"] == "Huile d'olive"
    assert first["unit"] == "kg"
    assert first["tier"] == 1
    assert first["saving_pct"] == pytest.approx(44.3)
    assert first["monthly_packs"] == pytest.approx(1.0)
    assert first["monthly_saving_eur"] == pytest.approx(6.85)


def test_recommendations_empty_is_200_not_error(make_client) -> None:
    # panier vide / aucun substitut -> 200 items=[]
    session = _FakeSession(_fake_user(), [])
    client = make_client(session)

    r = client.get("/me/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["total_monthly_saving_eur"] == 0.0


def test_recommendations_query_params_flow_to_sql(make_client) -> None:
    session = _FakeSession(_fake_user(), [])
    client = make_client(session)

    r = client.get("/me/recommendations?limit=5&max_tier=1&min_purchases=2")
    assert r.status_code == 200
    assert session.last_params is not None
    assert session.last_params["limit"] == 5
    assert session.last_params["max_tier"] == 1
    assert session.last_params["min_purchases"] == 2
    assert "6 months" in session.last_sql
    assert "product_substitutions" in session.last_sql


def test_recommendations_defaults_exclude_tier3(make_client) -> None:
    # defaut max_tier=2 : Tier 3 non expose
    session = _FakeSession(_fake_user(), [])
    client = make_client(session)

    r = client.get("/me/recommendations")
    assert r.status_code == 200
    assert session.last_params["max_tier"] == 2
