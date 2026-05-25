"""FastAPI app worker OCR — POST /push (Pub/Sub) → GCS → receipt_ocr → Cloud SQL."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from receipt_ocr.exceptions import ReceiptParseError

from .auth import verify_oidc
from .config import Settings, get_settings
from .gcs import ImageTooLargeError, download_image
from .logging import configure_logging, get_logger
from . import mapper, ocr, pg, pubsub
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
    title="prt-prod-worker-ocr",
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
        bucket, gcs_object_path = pubsub.parse_pubsub_envelope(body)
    except ValueError as exc:
        logger.warning("push_parse_failed", error=str(exc))
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    try:
        ticket_id = pubsub.extract_ticket_id(gcs_object_path)
        user_id = pubsub.extract_user_id(gcs_object_path)
    except ValueError as exc:
        logger.warning("push_path_invalid", error=str(exc), gcs_path=gcs_object_path)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(ticket_id=ticket_id)

    subscription = ""
    try:
        outer = json.loads(body)
        subscription = str(outer.get("subscription") or "")
    except json.JSONDecodeError:
        pass

    logger.info(
        "push_received",
        ticket_id=ticket_id,
        gcs_path=gcs_object_path,
        subscription=subscription,
        bucket=bucket,
    )

    claimed = await pg.set_ticket_processing(pool, ticket_id)
    if not claimed:
        logger.info(
            "ticket_already_processed",
            ticket_id=ticket_id,
            reason="idempotent_skip",
        )
        return Response(status_code=204)

    logger.info("ocr_start", ticket_id=ticket_id, engine=settings.prt_ocr_engine)
    t_start = time.monotonic()
    image_bytes = 0

    try:
        image_data = await download_image(bucket, gcs_object_path)
        image_bytes = len(image_data)
        ocr_result = await asyncio.to_thread(
            ocr.run_ocr,
            image_data,
            settings.prt_ocr_engine,
        )
        duration_ms = int((time.monotonic() - t_start) * 1000)

        ticket_fields = mapper.map_ticket_fields(
            ocr_result,
            ticket_id,
            gcs_object_path,
            settings.prt_ocr_engine,
            duration_ms,
            confidence=1.0,
        )
        prix_rows = mapper.map_prix_extraits_rows(ocr_result, ticket_id)

        await pg.set_ticket_done(pool, ticket_id, ticket_fields)
        await pg.upsert_prix_extraits(pool, prix_rows)

        logger.info(
            "pg_upsert_done",
            ticket_id=ticket_id,
            n_lines=len(prix_rows),
        )
        logger.info(
            "ocr_done",
            ticket_id=ticket_id,
            user_id=user_id,
            gcs_path=gcs_object_path,
            duration_ms=duration_ms,
            n_lines=len(prix_rows),
            n_resolved_vector=0,
            n_resolved_fuzzy=0,
            n_needs_validation=len(prix_rows),
            ocr_confidence=1.0,
            image_bytes=image_bytes,
            model_version=settings.prt_ocr_engine,
        )
        return Response(status_code=204)

    except (ImageTooLargeError, OcrProcessingError, ReceiptParseError, ValueError) as fatal_err:
        await pg.set_ticket_failed(pool, ticket_id, str(fatal_err))
        logger.warning(
            "ocr_failed",
            ticket_id=ticket_id,
            error=str(fatal_err),
            retryable=False,
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
