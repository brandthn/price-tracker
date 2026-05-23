"""FastAPI app worker OFF — POST /run orchestre tout le pipeline.

Découpage volontaire :
- discovery (BQ)
- fetch loop OFF (rate-limited, timeout-bounded)
- embeddings (Vertex)
- écritures (BQ MERGE + pg UPSERT en parallèle)
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime

from fastapi import Depends, FastAPI

from .auth import verify_oidc
from .bq import discover_eans_to_enrich, merge_catalogue
from .config import Settings, get_settings
from .logging import configure_logging, get_logger
from .off_client import OFFClient, OFFProduct
from .pg import open_pool, upsert_products
from .vertex import VertexEmbedder

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

app = FastAPI(
    title="prt-prod-worker-off",
    docs_url=None,
    redoc_url=None,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_project(settings: Settings) -> str:
    if settings.google_cloud_project:
        return settings.google_cloud_project
    import google.auth

    _, project = google.auth.default()
    if not project:
        raise RuntimeError("Cannot resolve GCP project_id.")
    return project


async def _fetch_loop(
    *,
    eans: list[str],
    client: OFFClient,
    deadline_monotonic: float,
) -> list[OFFProduct]:
    """Itère les EAN, respecte le timeout global du run, arrête proprement
    si on dépasse `deadline_monotonic`."""
    products: list[OFFProduct] = []
    for ean in eans:
        if time.monotonic() >= deadline_monotonic:
            logger.warning(
                "off_loop_deadline_reached",
                processed=len(products),
                remaining=len(eans) - len(products),
            )
            break
        try:
            product = await client.fetch_product(ean)
        except Exception as exc:  # noqa: BLE001
            # Une erreur sur un EAN ne doit pas faire échouer tout le batch.
            # On log et on continue ; cet EAN sera repicked au run suivant
            # (toujours absent de catalogue_produits).
            logger.error("off_fetch_failed", ean=ean, error=str(exc))
            continue
        products.append(product)
    return products


@app.post("/run")
async def run(_oidc: dict = Depends(verify_oidc)) -> dict[str, object]:
    t0 = time.monotonic()
    settings = get_settings()
    project_id = _resolve_project(settings)
    deadline = t0 + settings.prt_off_run_timeout_s

    logger.info(
        "run_start",
        project=project_id,
        rate_rpm=settings.prt_off_rate_rpm,
        max_eans=settings.prt_off_max_eans_per_run,
        timeout_s=settings.prt_off_run_timeout_s,
    )

    # 1) Discovery — sync (BQ client est sync)
    eans = await asyncio.to_thread(
        discover_eans_to_enrich,
        project_id=project_id,
        dataset=settings.prt_bq_dataset_silver,
        table_open_prices=settings.prt_bq_table_open_prices,
        table_catalogue=settings.prt_bq_table_catalogue,
        limit=settings.prt_off_max_eans_per_run,
    )
    if not eans:
        duration_s = round(time.monotonic() - t0, 2)
        logger.info("run_done_empty", duration_s=duration_s)
        return {
            "enqueued": 0,
            "off_found": 0,
            "off_not_found": 0,
            "embedded": 0,
            "rows_upserted_bq": 0,
            "rows_upserted_pg": 0,
            "duration_s": duration_s,
        }

    # 2) Fetch OFF — async, rate-limited
    async with OFFClient(
        base_url=settings.prt_off_base_url,
        user_agent=settings.prt_off_user_agent,
        rate_limit_rpm=settings.prt_off_rate_rpm,
        timeout_s=settings.prt_off_http_timeout_s,
        max_retries=settings.prt_off_max_retries,
    ) as off:
        products = await _fetch_loop(eans=eans, client=off, deadline_monotonic=deadline)

    found = [p for p in products if p.found]
    not_found = [p for p in products if not p.found]

    # 3) Embeddings Vertex — sync (SDK sync), uniquement pour les `found`
    embedder = VertexEmbedder(
        project=project_id,
        location=settings.prt_gcp_region,
        model_name=settings.prt_vertex_model,
        batch_size=settings.prt_vertex_batch,
        task_type=settings.prt_vertex_task_type,
        output_dim=settings.prt_vertex_output_dim,
    )
    embed_inputs = [p.embedding_text for p in found]
    embeddings_found = await asyncio.to_thread(embedder.embed, embed_inputs)

    # Recombine : products[] et embeddings[] alignés (None pour not_found)
    by_ean_emb: dict[str, list[float]] = {
        p.ean: emb for p, emb in zip(found, embeddings_found, strict=True)
    }
    embeddings = [by_ean_emb.get(p.ean) for p in products]

    # 4a) BQ MERGE
    enriched_at_iso = datetime.now(UTC).isoformat()
    bq_rows = await asyncio.to_thread(
        merge_catalogue,
        project_id=project_id,
        dataset=settings.prt_bq_dataset_silver,
        table=settings.prt_bq_table_catalogue,
        products=products,
        enriched_at_iso=enriched_at_iso,
    )

    # 4b) pg UPSERT
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
            pool, products=products, embeddings=embeddings
        )
    finally:
        await pool.close()

    duration_s = round(time.monotonic() - t0, 2)
    logger.info(
        "run_done",
        enqueued=len(eans),
        off_found=len(found),
        off_not_found=len(not_found),
        embedded=len(embeddings_found),
        rows_upserted_bq=bq_rows,
        rows_upserted_pg=pg_rows,
        duration_s=duration_s,
    )
    return {
        "enqueued": len(eans),
        "off_found": len(found),
        "off_not_found": len(not_found),
        "embedded": len(embeddings_found),
        "rows_upserted_bq": bq_rows,
        "rows_upserted_pg": pg_rows,
        "duration_s": duration_s,
    }
