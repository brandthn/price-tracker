#Load a bulk OFF artifact into BigQuery and Cloud SQL

from __future__ import annotations

import asyncio
import gzip
import io
import json
import os
import sys
import time
from datetime import UTC, datetime

from google.cloud import storage

from .bq import merge_catalogue
from .config import Settings, get_settings
from .logging import configure_logging, get_logger
from .off_client import OFFProduct
from .pg import open_pool, upsert_products

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

_DUMP_SOURCE = "openfoodfacts_dump"
_PRODUCT_FIELDS = (
    "ean", "name", "brand", "category_l1", "category_l2", "category_l3",
    "nutriscore", "nova", "ecoscore", "image_url", "found",
)
_RECO_FIELDS = (
    "quantity", "product_quantity", "product_quantity_unit", "categories_tags",
)


def _resolve_project(settings: Settings) -> str:
    if settings.google_cloud_project:
        return settings.google_cloud_project
    import google.auth

    _, project = google.auth.default()
    if not project:
        raise RuntimeError("Cannot resolve GCP project_id.")
    return project


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise SystemExit(f"URI GCS invalide (attendu gs://bucket/path): {uri!r}")
    bucket, _, blob = uri[len("gs://"):].partition("/")
    if not bucket or not blob:
        raise SystemExit(f"URI GCS invalide (bucket/blob manquant): {uri!r}")
    return bucket, blob


def read_artifact(gcs_uri: str) -> tuple[list[OFFProduct], list[list[float] | None]]:
    bucket_name, blob_name = _parse_gs_uri(gcs_uri)
    client = storage.Client()
    raw = client.bucket(bucket_name).blob(blob_name).download_as_bytes()

    products: list[OFFProduct] = []
    embeddings: list[list[float] | None] = []
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            products.append(
                OFFProduct(
                    **{k: rec[k] for k in _PRODUCT_FIELDS},
                    **{k: rec.get(k) for k in _RECO_FIELDS},
                )
            )
            embeddings.append(rec.get("embedding"))
    logger.info(
        "artifact_read",
        gcs_uri=gcs_uri,
        rows=len(products),
        with_embedding=sum(e is not None for e in embeddings),
    )
    return products, embeddings


async def load(gcs_uri: str) -> dict[str, object]:
    t0 = time.monotonic()
    settings = get_settings()
    project_id = _resolve_project(settings)

    products, embeddings = await asyncio.to_thread(read_artifact, gcs_uri)
    if not products:
        logger.warning("artifact_empty", gcs_uri=gcs_uri)
        return {"rows": 0, "rows_upserted_bq": 0, "rows_upserted_pg": 0, "duration_s": 0.0}

    # 1) BQ MERGE (réutilise le code worker)
    enriched_at_iso = datetime.now(UTC).isoformat()
    bq_rows = await asyncio.to_thread(
        merge_catalogue,
        project_id=project_id,
        dataset=settings.prt_bq_dataset_silver,
        table=settings.prt_bq_table_catalogue,
        products=products,
        enriched_at_iso=enriched_at_iso,
        source=_DUMP_SOURCE,
    )

    # 2) Cloud SQL UPSERT (réutilise le code worker) — nécessite le VPC
    pool = await open_pool(
        host=settings.prt_pg_host,
        port=settings.prt_pg_port,
        db=settings.prt_pg_db,
        user=settings.prt_pg_user,
        password=settings.prt_pg_password,
        max_size=settings.prt_pg_pool_size,
    )
    try:
        pg_rows = await upsert_products(
            pool, products=products, embeddings=embeddings, source=_DUMP_SOURCE
        )
    finally:
        await pool.close()

    duration_s = round(time.monotonic() - t0, 2)
    logger.info(
        "load_done",
        rows=len(products),
        rows_upserted_bq=bq_rows,
        rows_upserted_pg=pg_rows,
        duration_s=duration_s,
    )
    return {
        "rows": len(products),
        "rows_upserted_bq": bq_rows,
        "rows_upserted_pg": pg_rows,
        "duration_s": duration_s,
    }


def main() -> int:
    gcs_uri = os.environ.get("PRT_OFF_ARTIFACT_URI") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not gcs_uri:
        raise SystemExit("PRT_OFF_ARTIFACT_URI (env) ou argv[1] requis (gs://...).")
    result = asyncio.run(load(gcs_uri))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
