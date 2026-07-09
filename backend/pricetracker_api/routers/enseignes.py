"""Router enseignes public — comparateur de cherté relative (matched-basket).

Chiffre unique et honnête : l'indice de cherté relative. Pour chaque produit
relevé dans ≥2 enseignes sur la fenêtre, on compare le prix médian de l'enseigne
à la médiane inter-enseignes du produit ; l'indice de l'enseigne est la médiane
de ces ratios ×100. 100 = au niveau médian, <100 = moins chère, >100 = plus
chère. Le mix de produits ne fausse pas l'indice (comparaison produit par
produit), contrairement à un prix médian brut par enseigne.

L'« évolution des prix par enseigne » n'est PAS exposée (décision produit
2026-07-09) : l'index base-100 brut de `indices_inflation` est dominé par
l'assortiment (la médiane hebdo dépend des produits scannés cette semaine, pas
des prix), et une évolution honnête « à panier constant » manque de données à ce
volume. La question « ça monte où ? » reste répondue au niveau produit.

Noms résolus contre Cloud SQL `products` (catalogue de référence), jamais un EAN
nu. `query_dicts_safe` tolère une table Silver vide → panorama vide (200).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from google.cloud import bigquery
from sqlalchemy.ext.asyncio import AsyncSession

from .. import bq
from ..config import get_settings
from ..db import get_session
from ..schemas.enseignes import (
    EnseigneDetailOut,
    EnseigneProductRank,
    EnseigneSummary,
    EnseignesOut,
)
from ..services.catalog import resolve_products

router = APIRouter(prefix="/enseignes", tags=["enseignes"])

_DEFAULT_WINDOW_WEEKS = 12
_DEFAULT_MIN_MATCHED = 5  # calé sur données prod : 7 enseignes reconnaissables passent le seuil
_MIN_PRICE_OBS = 2  # relevés min par (produit, enseigne) pour retenir un prix médian
_TOP_PRODUCTS = 8  # nb de produits listés dans cheaper / dearer sur la fiche
_COUNTRY = "FR"


def _silver_fq() -> str:
    settings = get_settings()
    return bq.qualified(settings.prt_bq_dataset_silver, "open_prices_clean")


def _matched_cte(window_weeks: int) -> str:
    """CTE partagée panorama/fiche : prix médians appariés produit par produit.

    - `ens`    : prix médian + nb relevés par (produit, enseigne), fenêtre glissante.
    - `ref`    : prix de référence du produit = médiane inter-enseignes (produits
                 vus dans ≥2 enseignes seulement → comparaison possible).
    - `ratios` : prix enseigne / prix référence, par (enseigne, produit).
    """
    silver = _silver_fq()
    return f"""
    ens AS (
      SELECT
        product_code,
        store_brand_normalized AS enseigne,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS p,
        COUNT(*) AS n
      FROM {silver}
      WHERE country_code = '{_COUNTRY}'
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
        AND product_code IS NOT NULL
        AND store_brand_normalized IS NOT NULL
        AND week_start_date >= DATE_SUB(
          (SELECT MAX(week_start_date) FROM {silver}),
          INTERVAL {int(window_weeks)} WEEK)
      GROUP BY product_code, enseigne
      HAVING COUNT(*) >= {_MIN_PRICE_OBS}
    ),
    ref AS (
      SELECT
        product_code,
        APPROX_QUANTILES(p, 100)[OFFSET(50)] AS ref_p,
        COUNT(*) AS n_ens
      FROM ens
      GROUP BY product_code
      HAVING COUNT(*) >= 2
    ),
    ratios AS (
      SELECT
        e.enseigne,
        e.product_code,
        e.p,
        r.ref_p,
        e.n,
        SAFE_DIVIDE(e.p, r.ref_p) AS ratio
      FROM ens e
      JOIN ref r USING (product_code)
    )
    """


@router.get("", response_model=EnseignesOut)
async def get_enseignes(
    window_weeks: int = Query(default=_DEFAULT_WINDOW_WEEKS, ge=4, le=52),
    min_matched: int = Query(default=_DEFAULT_MIN_MATCHED, ge=1, le=100),
) -> EnseignesOut:
    """Panorama : classement des enseignes par cherté relative.

    Ne dépend que de BigQuery (les noms d'enseignes sont déjà lisibles) → la
    vitrine reste disponible même si Cloud SQL est indisponible. Une enseigne
    sous le seuil `min_matched` reste listée (transparence) mais avec
    `cherte_index=None` (« couverture insuffisante »)."""
    sql = f"""
    WITH {_matched_cte(window_weeks)}
    SELECT
      enseigne,
      APPROX_QUANTILES(ratio, 100)[OFFSET(50)] * 100 AS cherte_index,
      COUNT(*) AS matched_products,
      SUM(n) AS observations
    FROM ratios
    GROUP BY enseigne
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe, sql, context="enseignes_panorama"
    )

    items: list[EnseigneSummary] = []
    for r in rows:
        matched = int(r["matched_products"])
        has_index = matched >= min_matched and r.get("cherte_index") is not None
        items.append(
            EnseigneSummary(
                enseigne=r["enseigne"],
                cherte_index=round(float(r["cherte_index"]), 1) if has_index else None,
                matched_products=matched,
                observations=int(r["observations"]) if r.get("observations") is not None else None,
            )
        )

    # Classables (indice non nul) triés par cherté croissante (la moins chère en
    # tête), puis le reste par couverture décroissante.
    items.sort(
        key=lambda it: (
            it.cherte_index is None,
            it.cherte_index if it.cherte_index is not None else 0.0,
            -it.matched_products,
        )
    )

    return EnseignesOut(
        window_weeks=window_weeks,
        min_matched=min_matched,
        items=items,
    )


def _enseigne_exists(enseigne: str) -> bool:
    """L'enseigne a-t-elle au moins un relevé (pour distinguer « non suivie »)."""
    sql = f"""
    SELECT 1 FROM {_silver_fq()}
    WHERE country_code = '{_COUNTRY}' AND store_brand_normalized = @enseigne
    LIMIT 1
    """
    rows = bq.query_dicts_safe(
        sql,
        params=[bigquery.ScalarQueryParameter("enseigne", "STRING", enseigne)],
        context="enseignes_exists",
    )
    return len(rows) > 0


def _product_rank(r: dict, resolved: dict[str, dict]) -> EnseigneProductRank:
    ean = r.get("ean")
    cat = resolved.get(ean) if ean else None
    return EnseigneProductRank(
        ean=ean,
        produit_nom=(cat or {}).get("name"),
        brand=(cat or {}).get("brand"),
        image_url=(cat or {}).get("image_url"),
        in_catalog=cat is not None,
        price_eur=round(float(r["price_eur"]), 2) if r.get("price_eur") is not None else None,
        ref_price_eur=round(float(r["ref_price_eur"]), 2) if r.get("ref_price_eur") is not None else None,
        delta_pct=round(float(r["delta_pct"]), 1) if r.get("delta_pct") is not None else 0.0,
    )


@router.get("/{nom}", response_model=EnseigneDetailOut)
async def get_enseigne_detail(
    nom: str,
    window_weeks: int = Query(default=_DEFAULT_WINDOW_WEEKS, ge=4, le=52),
    min_matched: int = Query(default=_DEFAULT_MIN_MATCHED, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> EnseigneDetailOut:
    """Fiche enseigne : positionnement cherté + produits où elle est la moins /
    plus chère. Enseigne inconnue → payload « non suivie » (jamais un 404 brut)."""
    enseigne = nom.strip()
    # `agg` réutilise la MÊME expression APPROX_QUANTILES que le panorama →
    # l'indice de la fiche est strictement identique à celui du comparateur
    # (joint par CROSS JOIN, constant sur toutes les lignes).
    sql = f"""
    WITH {_matched_cte(window_weeks)},
    agg AS (
      SELECT
        APPROX_QUANTILES(ratio, 100)[OFFSET(50)] * 100 AS cherte_index,
        COUNT(*) AS matched_products,
        SUM(n) AS observations
      FROM ratios
      WHERE enseigne = @enseigne
    )
    SELECT
      r.product_code AS ean,
      r.p AS price_eur,
      r.ref_p AS ref_price_eur,
      r.ratio,
      (r.ratio - 1) * 100 AS delta_pct,
      a.cherte_index,
      a.matched_products,
      a.observations
    FROM ratios r
    CROSS JOIN agg a
    WHERE r.enseigne = @enseigne
    ORDER BY r.ratio ASC
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        sql,
        params=[bigquery.ScalarQueryParameter("enseigne", "STRING", enseigne)],
        context="enseignes_detail",
    )

    if not rows:
        # Aucun produit apparié : soit l'enseigne existe mais n'a pas assez de
        # relevés comparables, soit elle n'est pas suivie du tout.
        exists = await asyncio.to_thread(_enseigne_exists, enseigne)
        return EnseigneDetailOut(
            enseigne=enseigne,
            tracked=exists,
            window_weeks=window_weeks,
            min_matched=min_matched,
        )

    agg = rows[0]
    matched = int(agg["matched_products"])
    observations = int(agg["observations"]) if agg.get("observations") is not None else None
    cherte_index = (
        round(float(agg["cherte_index"]), 1)
        if matched >= min_matched and agg.get("cherte_index") is not None
        else None
    )

    # rows triés par ratio ASC : les moins chères (ratio<1) en tête, les plus
    # chères (ratio>1) en fin → on inverse ces dernières (plus chère d'abord).
    cheaper_rows = [
        r for r in rows if r.get("delta_pct") is not None and float(r["delta_pct"]) < 0
    ][:_TOP_PRODUCTS]
    dearer_rows = [
        r for r in rows if r.get("delta_pct") is not None and float(r["delta_pct"]) > 0
    ]
    dearer_rows = list(reversed(dearer_rows))[:_TOP_PRODUCTS]

    eans = [r["ean"] for r in (cheaper_rows + dearer_rows) if r.get("ean")]
    resolved = await resolve_products(session, eans)

    return EnseigneDetailOut(
        enseigne=enseigne,
        tracked=True,
        cherte_index=cherte_index,
        matched_products=matched,
        observations=observations,
        window_weeks=window_weeks,
        min_matched=min_matched,
        cheaper=[_product_rank(r, resolved) for r in cheaper_rows],
        dearer=[_product_rank(r, resolved) for r in dearer_rows],
    )
