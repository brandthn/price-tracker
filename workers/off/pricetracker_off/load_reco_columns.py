"""Loader « socle reco » — backfill quantité + chemin catégories (Étapes 1+2).

Lit l'artefact `enriched.jsonl.gz` (produit en local par `bulk/enrich.py --found-only`,
uploadé sur GCS) et met à jour **uniquement** les colonnes socle reco de
`products` (Cloud SQL) :

    UPDATE products SET quantity_raw = …, quantity_value = …, quantity_unit = …,
                        categories_tags = … WHERE ean = …

Différence avec `load_artifact` (upsert complet) :
  - NE touche PAS BQ `catalogue_produits` ;
  - NE touche AUCUNE autre colonne de `products` (name/brand/image_url/scores/
    embedding/source/enriched_at) → zéro régression sur les données curées (dont
    l'import Maty). Même garde-fou que `load_embeddings`.

Sert à alimenter les ~12 k produits DÉJÀ en base après la migration 0005. Le
worker quotidien, lui, écrit ces colonnes à l'upsert des nouveaux EAN.

DOIT tourner **sur Cloud, dans le VPC** : la private IP de Cloud SQL est
injoignable en local. Conçu comme un **Cloud Run Job** réutilisant l'image + le
code du worker OFF.

Config : mêmes env vars PG que le worker (`PRT_PG_*`, `GOOGLE_CLOUD_PROJECT`).
URI de l'artefact : `PRT_OFF_ARTIFACT_URI` (ou argv[1]), ex:
    gs://price-tracker-prod-01-silver/off-bulk/off_reco_backfill.jsonl.gz

Lancement (Cloud Run Job) :
    python -m pricetracker_off.load_reco_columns
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from .config import get_settings
from .load_artifact import read_artifact
from .logging import configure_logging, get_logger
from .pg import open_pool, update_reco_columns

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


async def load(gcs_uri: str) -> dict[str, object]:
    t0 = time.monotonic()
    settings = get_settings()

    products, _embeddings = await asyncio.to_thread(read_artifact, gcs_uri)
    if not products:
        logger.warning("artifact_empty", gcs_uri=gcs_uri)
        return {"rows": 0, "candidates": 0, "updated": 0, "duration_s": 0.0}

    pool = await open_pool(
        host=settings.prt_pg_host,
        port=settings.prt_pg_port,
        db=settings.prt_pg_db,
        user=settings.prt_pg_user,
        password=settings.prt_pg_password,
        max_size=settings.prt_pg_pool_size,
    )
    try:
        result = await update_reco_columns(pool, products=products)
    finally:
        await pool.close()

    duration_s = round(time.monotonic() - t0, 2)
    out: dict[str, object] = {
        "rows": len(products),
        "candidates": result["candidates"],
        "updated": result["updated"],
        "duration_s": duration_s,
    }
    logger.info("reco_backfill_done", **out)
    return out


def main() -> int:
    gcs_uri = os.environ.get("PRT_OFF_ARTIFACT_URI") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not gcs_uri:
        raise SystemExit("PRT_OFF_ARTIFACT_URI (env) ou argv[1] requis (gs://...).")
    result = asyncio.run(load(gcs_uri))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
