"""FastAPI app worker OCR backend PaddleOCR — POST /push (Pub/Sub `ocr-paddle`).

Contrat identique aux workers OCR existants : on reçoit un ticket_id, on lit
l'image sur GCS, on OCR, on écrit `prix_extraits` + `tickets`. 204 = ACK
(succès ou échec déterministe), 5xx = NACK (erreur transitoire → retry → DLQ).
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
from pricetracker_receipt_pipeline.worker import mapper, pg, pubsub
from pricetracker_receipt_pipeline.worker.auth import build_verify_oidc
from pricetracker_receipt_pipeline.worker.gcs import (
    ImageTooLargeError,
    download_image,
    split_gs_uri,
)
from pricetracker_receipt_pipeline.worker.logging import configure_logging, get_logger

from . import ocr
from .config import get_settings
from .ocr import OcrProcessingError

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

verify_oidc = build_verify_oidc(get_settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Le backend est construit une seule fois : PaddleOCR charge ses modèles de
    # détection/reconnaissance (baked dans l'image). Un échec ici fait échouer le
    # démarrage → Cloud Run relance, aucun message n'est ACKé par un worker KO.
    app.state.backend = await asyncio.to_thread(ocr.build_backend)
    logger.info("backend_ready", engine=settings.prt_ocr_engine_label)

    pool = await pg.create_pool(settings)
    app.state.pool = pool
    logger.info("pg_pool_ready", host=settings.prt_pg_host, db=settings.prt_pg_db)
    try:
        yield
    finally:
        await pool.close()
        logger.info("pg_pool_closed")


app = FastAPI(
    title="prt-prod-worker-ocr-paddle",
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
    backend = request.app.state.backend

    try:
        ticket_id = pubsub.parse_push_envelope(body)
    except ValueError as exc:
        logger.warning("push_parse_failed", error=str(exc))
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(ticket_id=ticket_id)

    row = await pg.get_ticket(pool, ticket_id)
    if row is None:
        logger.warning("ticket_missing", ticket_id=ticket_id)
        return Response(status_code=204)

    model = settings.prt_ocr_engine_label
    logger.info("ocr_start", ticket_id=ticket_id, model=model)
    t_start = time.monotonic()

    try:
        bucket, object_path = split_gs_uri(row["gcs_path"])
        image_data = await download_image(bucket, object_path)

        ocr_result = await asyncio.to_thread(ocr.run_ocr, backend, image_data)
        duration_ms = int((time.monotonic() - t_start) * 1000)

        ticket_fields = mapper.map_ticket_fields(
            ocr_result,
            ticket_id,
            object_path,
            settings.prt_ocr_engine_label,
            duration_ms,
            confidence=1.0,
        )
        prix_rows = mapper.map_prix_extraits_rows(ocr_result, ticket_id)

        # Résolution EAN via product_aliases (lecture seule). MÊME fonction et
        # MÊME point que les workers OCR existants (juste après
        # map_prix_extraits_rows, avant l'écriture) → comportement identique.
        match_stats = await alias_lookup.resolve_line_eans(
            pool, ticket_fields.get("enseigne"), prix_rows
        )

        # Écriture ATOMIQUE (delete → insert → bump ocr_attempts) en une seule
        # transaction : le poll frontend ne voit jamais un état mi-écrit.
        await pg.persist_result(pool, ticket_id, ticket_fields, model, prix_rows)

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
        # Échec déterministe : on ACK (204) pour ne pas boucler, sans toucher
        # au ticket (un éventuel résultat précédent reste valable).
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
