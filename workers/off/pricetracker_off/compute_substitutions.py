"""Calcul plein-catalogue des paires substitut→produit (reco Étape 2).

Étape SÉPARÉE de la boucle d'enrichissement quotidienne (§5.5 handoff) : conçu
comme un **Cloud Run Job** dans le VPC réutilisant l'image `off` (qui a le client
BQ ET le pool Cloud SQL).

Pipeline :
  1. médian prix/EAN depuis BQ `open_prices_clean` (fenêtre 12 mois, ≥1 obs) ;
  2. produits scorables (embedding + quantité) + kNN pgvector depuis Cloud SQL ;
  3. pour chaque source : €/unité, accord catégoriel, score (catégorie dominante /
     embedding borné), on garde les substituts MOINS CHERS au €/unité, top-N,
     diversité de marque ;
  4. TRUNCATE + INSERT `product_substitutions` (Cloud SQL).

Un **échantillon de paires** est loggué (noms, cosinus, cat_agree, tier, €/unité,
économie) → réglage des knobs « à l'œil sur du réel » sans lire Cloud SQL en local.

Config : mêmes env vars que le worker (`PRT_PG_*`, `PRT_BQ_*`, `PRT_RECO_*`,
`GOOGLE_CLOUD_PROJECT`). Lancement (Cloud Run Job) :
    python -m pricetracker_off.compute_substitutions
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Any

from .bq import fetch_median_prices
from .config import Settings, get_settings
from .knn import compute_knn_pairs
from .logging import configure_logging, get_logger
from .pg import fetch_scorable_products, open_pool, write_substitutions
from .substitutions import (
    RawCandidate,
    ScoreWeights,
    category_agreement,
    rank_substitutes,
)

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

_SAMPLE_SIZE = 30


def _resolve_project(settings: Settings) -> str:
    if settings.google_cloud_project:
        return settings.google_cloud_project
    import google.auth

    _, project = google.auth.default()
    if not project:
        raise RuntimeError("Cannot resolve GCP project_id.")
    return project


def _weights(s: Settings) -> ScoreWeights:
    return ScoreWeights(
        w_cat=s.prt_reco_w_cat,
        w_emb=s.prt_reco_w_emb,
        cos_floor=s.prt_reco_cos_floor,
        cos_ref=s.prt_reco_cos_ref,
        tier1_cat=s.prt_reco_tier1_cat,
        tier2_cat=s.prt_reco_tier2_cat,
    )


def _build_rows(
    products: dict[str, dict[str, Any]],
    prices: dict[str, tuple[float, int]],
    pairs: list[tuple[str, str, float]],
    s: Settings,
) -> tuple[list[tuple[Any, ...]], list[dict[str, Any]], Counter]:
    """Assemble les lignes `product_substitutions` + un échantillon lisible +
    la distribution des tiers. Pur (testable, sans I/O)."""
    weights = _weights(s)
    by_source: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for src_ean, tgt_ean, cosine in pairs:
        by_source[src_ean].append((tgt_ean, cosine))

    rows: list[tuple[Any, ...]] = []
    sample: list[dict[str, Any]] = []
    tier_counts: Counter = Counter()

    for src_ean, cand_list in by_source.items():
        src = products.get(src_ean)
        src_price = prices.get(src_ean)
        if src is None or src_price is None:
            continue
        src_qty = src["quantity_value"]
        if not src_qty > 0:
            continue
        src_ppu = src_price[0] / src_qty
        src_obs = src_price[1]

        raw: list[RawCandidate] = []
        for tgt_ean, cosine in cand_list:
            tgt = products.get(tgt_ean)
            tgt_price = prices.get(tgt_ean)
            if tgt is None or tgt_price is None:
                continue
            tgt_qty = tgt["quantity_value"]
            if not tgt_qty > 0:
                continue
            cat = category_agreement(
                src["category_l3"], tgt["category_l3"],
                src["categories_tags"], tgt["categories_tags"],
            )
            raw.append(
                RawCandidate(
                    target_ean=tgt_ean,
                    cosine=cosine,
                    cat_agree=cat,
                    target_ppu=tgt_price[0] / tgt_qty,
                    target_obs=tgt_price[1],
                    target_brand=tgt["brand"],
                )
            )

        subs = rank_substitutes(
            src_ppu, raw, w=weights,
            top_n=s.prt_reco_top_n, max_per_brand=s.prt_reco_max_per_brand,
        )
        for sub in subs:
            tier_counts[sub.tier] += 1
            rows.append(
                (
                    src_ean, sub.target_ean, sub.tier, sub.score, sub.cosine,
                    sub.cat_agreement, src["quantity_unit"], round(src_ppu, 4),
                    sub.target_ppu, sub.saving_per_unit, sub.saving_pct,
                    src_obs, sub.target_obs,
                )
            )
            if len(sample) < _SAMPLE_SIZE:
                tgt = products[sub.target_ean]
                sample.append(
                    {
                        "src": src["name"], "tgt": tgt["name"],
                        "unit": src["quantity_unit"], "tier": sub.tier,
                        "score": sub.score, "cos": sub.cosine, "cat": sub.cat_agreement,
                        "src_ppu": round(src_ppu, 3), "tgt_ppu": sub.target_ppu,
                        "save_pct": round(sub.saving_pct * 100, 1),
                    }
                )

    return rows, sample, tier_counts


async def compute() -> dict[str, object]:
    t0 = time.monotonic()
    settings = get_settings()
    project_id = _resolve_project(settings)

    prices = await asyncio.to_thread(
        fetch_median_prices,
        project_id=project_id,
        dataset=settings.prt_bq_dataset_silver,
        table_open_prices=settings.prt_bq_table_open_prices,
        window_weeks=settings.prt_reco_price_window_weeks,
        min_obs=settings.prt_reco_price_min_obs,
    )

    pool = await open_pool(
        host=settings.prt_pg_host,
        port=settings.prt_pg_port,
        db=settings.prt_pg_db,
        user=settings.prt_pg_user,
        password=settings.prt_pg_password,
        max_size=settings.prt_pg_pool_size,
    )
    try:
        products, eans, embeddings = await fetch_scorable_products(pool)
        # Sources = produits scorables AYANT un prix (sans prix, pas d'économie à
        # calculer → inutile de chercher leurs voisins). Candidats = tous.
        priced_sources = {ean for ean in eans if ean in prices}
        units = [products[ean]["quantity_unit"] for ean in eans]
        # kNN EN MÉMOIRE (BLAS) — pas d'ANN pgvector en batch (cf. knn.py).
        pairs = await asyncio.to_thread(
            compute_knn_pairs,
            eans, embeddings, units,
            source_eans=priced_sources, k=settings.prt_reco_knn_k,
        )
        rows, sample, tier_counts = _build_rows(products, prices, pairs, settings)
        written = await write_substitutions(pool, rows)
    finally:
        await pool.close()

    sources_with_subs = len({r[0] for r in rows})
    duration_s = round(time.monotonic() - t0, 2)
    result = {
        "priced_eans": len(prices),
        "scorable_products": len(products),
        "priced_sources": len(priced_sources),
        "knn_pairs": len(pairs),
        "substitutions_written": written,
        "sources_with_substitutes": sources_with_subs,
        "tier_1": tier_counts.get(1, 0),
        "tier_2": tier_counts.get(2, 0),
        "tier_3": tier_counts.get(3, 0),
        "duration_s": duration_s,
    }
    logger.info("compute_substitutions_done", **result)
    # Échantillon lisible pour régler les knobs (DoD §7).
    for e in sample:
        logger.info("substitution_sample", **e)
    return result


def main() -> int:
    result = asyncio.run(compute())
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
