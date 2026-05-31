"""Router observatoire public — rankings, hall of shame, carte.

Tous les endpoints lisent BQ Gold (`rankings_produits`, `aggregats_enseignes`,
`indices_inflation`). Si les tables ne sont pas encore peuplées (worker
indices pas encore tourné), on renvoie un payload vide (200, items=[])
plutôt que 500 : c'est le contrat utile pour le frontend qui peut afficher
"Données en cours de calcul".
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from .. import bq
from ..config import get_settings
from ..schemas.indices import (
    MapDepartementValue,
    MapOut,
    RankingItem,
    RankingsOut,
)

router = APIRouter(prefix="/observatoire", tags=["observatoire"])


def _row_to_ranking(r: dict) -> RankingItem:
    return RankingItem(
        ean=r.get("ean"),
        produit_nom=r.get("produit_nom") or r.get("name"),
        brand=r.get("brand"),
        pct_change=float(r["pct_change"]) if r.get("pct_change") is not None else 0.0,
        price_eur_current=r.get("price_eur_current"),
        price_eur_previous=r.get("price_eur_previous"),
        sample_size=r.get("sample_size"),
    )


@router.get("/rankings", response_model=RankingsOut)
async def get_rankings(limit: int = Query(default=20, ge=1, le=100)) -> RankingsOut:
    settings = get_settings()
    sql = f"""
    SELECT ean, produit_nom, brand, pct_change, price_eur_current,
           price_eur_previous, sample_size, period
    FROM {bq.qualified(settings.prt_bq_dataset_gold, 'rankings_produits')}
    WHERE category = 'top_increases'
    ORDER BY pct_change DESC
    LIMIT {int(limit)}
    """
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context="observatoire_rankings")
    period = rows[0].get("period") if rows else None
    return RankingsOut(period=period, items=[_row_to_ranking(r) for r in rows])


@router.get("/hall-of-shame", response_model=RankingsOut)
async def get_hall_of_shame(limit: int = Query(default=20, ge=1, le=100)) -> RankingsOut:
    """Produits en hausse les plus achetés (croise pct_change + popularité).
    Le scoring est fait côté worker indices (colonne `shame_score`).
    """
    settings = get_settings()
    sql = f"""
    SELECT ean, produit_nom, brand, pct_change, price_eur_current,
           price_eur_previous, sample_size, period
    FROM {bq.qualified(settings.prt_bq_dataset_gold, 'rankings_produits')}
    WHERE category = 'hall_of_shame'
    ORDER BY shame_score DESC
    LIMIT {int(limit)}
    """
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context="observatoire_hall_of_shame")
    period = rows[0].get("period") if rows else None
    return RankingsOut(period=period, items=[_row_to_ranking(r) for r in rows])


@router.get("/map", response_model=MapOut)
async def get_map() -> MapOut:
    """Données choroplèthe : inflation par département FR.

    Source : `indices_inflation` filtré sur `scope='regional'` à la date la
    plus récente. Renvoie vide tant que worker indices n'a pas tourné.
    """
    settings = get_settings()
    sql = f"""
    WITH latest AS (
        SELECT MAX(date) AS d
        FROM {bq.qualified(settings.prt_bq_dataset_gold, 'indices_inflation')}
        WHERE scope = 'regional'
    )
    SELECT i.departement, i.value AS inflation_pct, i.sample_size,
           CAST(latest.d AS STRING) AS period
    FROM {bq.qualified(settings.prt_bq_dataset_gold, 'indices_inflation')} i, latest
    WHERE i.scope = 'regional' AND i.date = latest.d
    """
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context="observatoire_map")
    period = rows[0].get("period") if rows else None
    values = [
        MapDepartementValue(
            departement=r["departement"],
            inflation_pct=float(r["inflation_pct"]) if r.get("inflation_pct") is not None else None,
            sample_size=r.get("sample_size"),
        )
        for r in rows
        if r.get("departement")
    ]
    return MapOut(period=period, values=values)
