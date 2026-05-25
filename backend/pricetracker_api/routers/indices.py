"""Router indices — perso, national, régional.

Les tables BQ Gold (`indices_inflation`) sont alimentées par le worker
indices (Phase 9). Tant qu'elles n'existent pas / sont vides, on renvoie
un payload `series=[]` avec `current=None` plutôt que de planter — c'est
le contrat le plus utile pour le frontend (rendu placeholder).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from google.cloud import bigquery

from .. import bq
from ..auth import AuthenticatedUser, verify_bearer
from ..config import get_settings
from ..schemas.indices import IndexPoint, InflationIndexOut

router = APIRouter(prefix="/indices", tags=["indices"])

_INDICES_TABLE = "indices_inflation"


def _build_index(scope: str, rows: list[dict]) -> InflationIndexOut:
    series = [
        IndexPoint(
            date=r["date"] if not isinstance(r["date"], str) else r["date"],
            value=float(r["value"]) if r.get("value") is not None else 0.0,
            sample_size=r.get("sample_size"),
        )
        for r in rows
        if r.get("value") is not None
    ]
    current = series[-1].value if series else None
    base_period = rows[0].get("base_period") if rows else None
    insee = rows[-1].get("insee_comparison") if rows else None
    return InflationIndexOut(
        scope=scope,
        base_period=base_period,
        current=current,
        series=series,
        insee_comparison=float(insee) if insee is not None else None,
    )


@router.get("/national", response_model=InflationIndexOut)
async def get_national() -> InflationIndexOut:
    settings = get_settings()
    sql = f"""
    SELECT date, value, sample_size, base_period, insee_comparison
    FROM {bq.qualified(settings.prt_bq_dataset_gold, _INDICES_TABLE)}
    WHERE scope = 'national'
    ORDER BY date
    """
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context="indices_national")
    return _build_index("national", rows)


@router.get("/regional/{departement}", response_model=InflationIndexOut)
async def get_regional(departement: str) -> InflationIndexOut:
    settings = get_settings()
    sql = f"""
    SELECT date, value, sample_size, base_period, insee_comparison
    FROM {bq.qualified(settings.prt_bq_dataset_gold, _INDICES_TABLE)}
    WHERE scope = 'regional' AND departement = @dept
    ORDER BY date
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        sql,
        params=[bigquery.ScalarQueryParameter("dept", "STRING", departement)],
        context=f"indices_regional_{departement}",
    )
    return _build_index(f"regional:{departement}", rows)


@router.get("/personal", response_model=InflationIndexOut)
async def get_personal(
    user: AuthenticatedUser = Depends(verify_bearer),
) -> InflationIndexOut:
    """Indice personnel : panier de l'utilisateur (`user_basket_history`)
    croisé avec les prix Gold. Implémentation V1 : on lit la table
    `indices_inflation` filtré sur `scope='personal' AND firebase_uid=@uid`.
    Le worker indices (Phase 9) sera responsable de matérialiser cette vue.

    Tant que le worker n'a pas tourné, renvoie un payload `series=[]`.
    """
    settings = get_settings()
    sql = f"""
    SELECT date, value, sample_size, base_period
    FROM {bq.qualified(settings.prt_bq_dataset_gold, _INDICES_TABLE)}
    WHERE scope = 'personal' AND firebase_uid = @uid
    ORDER BY date
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        sql,
        params=[bigquery.ScalarQueryParameter("uid", "STRING", user.uid)],
        context=f"indices_personal_{user.uid}",
    )
    return _build_index("personal", rows)
