"""FastAPI app worker OCR tier-2 — POST /push (Pub/Sub `ocr-retry`).

Contrat identique au worker tier-1 : on reçoit un ticket, on fait l'OCR, that's
it. Ici, l'OCR = un LLM Groq avec prompt correctif qui réutilise l'extraction
précédente jugée erronée.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pricetracker_matching import alias_lookup

from . import mapper, ocr, pg, pubsub
from .auth import verify_oidc
from .config import get_settings
from .gcs import ImageTooLargeError, download_image, split_gs_uri
from .logging import configure_logging, get_logger
from .ocr import OcrProcessingError

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = await pg.create_pool(settings)
    app.state.pool = pool
    logger.info("pg_pool_ready", host=settings.prt_pg_host, db=settings.prt_pg_db)
    try:
        yield
    finally:
        await pool.close()
        logger.info("pg_pool_closed")


app = FastAPI(
    title="prt-prod-worker-ocr-llm",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/push")
async def push(
    request: Request,
    _oidc: dict = Depends(verify_oidc),
) -> Response:
    body = await request.body()
    settings = get_settings()
    pool: Any = request.app.state.pool

    try:
        ticket_id = pubsub.parse_retry_envelope(body)
    except ValueError as exc:
        logger.warning("push_parse_failed", error=str(exc))
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(ticket_id=ticket_id)

    row = await pg.get_ticket(pool, ticket_id)
    if row is None:
        logger.warning("ticket_missing", ticket_id=ticket_id)
        return Response(status_code=204)

    model = settings.prt_ocr_model
    logger.info("ocr_start", ticket_id=ticket_id, model=model, tier=2)
    t_start = time.monotonic()

    try:
        bucket, object_path = split_gs_uri(row["gcs_path"])
        image_data = await download_image(bucket, object_path)

        prev_rows = [dict(r) for r in await pg.fetch_prix_extraits(pool, ticket_id)]
        previous_json = ocr.build_previous_extraction_json(
            row["enseigne"], row["date_ticket"], prev_rows
        )

        ocr_result = await asyncio.to_thread(
            ocr.run_ocr, image_data, model, previous_json
        )
        duration_ms = int((time.monotonic() - t_start) * 1000)

        ticket_fields = mapper.map_ticket_fields(
            ocr_result,
            settings.prt_ocr_engine_label,
            duration_ms,
            confidence=1.0,
        )
        prix_rows = mapper.map_prix_extraits_rows(ocr_result, ticket_id)

        # Même étage EAN que le tier-1, au même endroit : juste après le mapping
        # et avant l'écriture, pour que les deux tiers se comportent pareil.
        match_stats = await alias_lookup.resolve_line_eans(
            pool, ticket_fields.get("enseigne"), prix_rows
        )

        # Une seule transaction : le poll du front ne doit jamais tomber sur un
        # état à moitié écrit, et si ça casse le résultat tier-1 reste en place.
        await pg.persist_tier2_result(
            pool, ticket_id, ticket_fields, model, prix_rows
        )

        logger.info(
            "ocr_done",
            ticket_id=ticket_id,
            model=model,
            duration_ms=duration_ms,
            n_lines=len(prix_rows),
            n_resolved_user=match_stats.n_resolved_user,
            n_resolved_catalogue=match_stats.n_resolved_catalogue,
            n_resolved_total=match_stats.n_resolved_total,
            n_needs_validation=match_stats.n_needs_validation,
            prev_attempts=row["ocr_attempts"],
        )
        return Response(status_code=204)

    except (ImageTooLargeError, OcrProcessingError, ValueError) as fatal_err:
        # Échec tier-2 : on NE touche pas au ticket (le résultat tier-1 reste
        # valable). On ack (204) pour ne pas boucler sur une erreur déterministe.
        logger.warning(
            "ocr_failed", ticket_id=ticket_id, error=str(fatal_err), retryable=False
        )
        return Response(status_code=204)

    except Exception as transient_err:
        logger.error(
            "ocr_failed",
            ticket_id=ticket_id,
            error=str(transient_err),
            retryable=True,
            exc_info=True,
        )
        raise
