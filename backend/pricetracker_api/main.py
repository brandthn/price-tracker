"""FastAPI app PriceTracker backend.

Lifecycle :
- startup : init structlog + SQLAlchemy engine + Firebase Admin (lazy à
  la 1ère vérif Bearer pour ne pas bloquer le démarrage si ADC manque
  en CI/tests).
- shutdown : dispose engine.

OpenAPI activable/désactivable via `PRT_OPENAPI_ENABLED` (validation Brandon :
laissé `true` en prod pour faciliter l'intégration frontend + soutenance).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import dispose_engine, init_engine
from .logging import configure_logging, get_logger
from .routers import indices, observatoire, products, stats, tickets, users


def _build_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.prt_log_level)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "app_starting",
            env=settings.prt_env,
            project=settings.google_cloud_project,
            region=settings.prt_gcp_region,
            openapi=settings.prt_openapi_enabled,
            auth_disable=settings.prt_auth_disable,
        )
        init_engine()
        try:
            yield
        finally:
            await dispose_engine()
            logger.info("app_stopped")

    docs_url = "/docs" if settings.prt_openapi_enabled else None
    redoc_url = "/redoc" if settings.prt_openapi_enabled else None
    openapi_url = "/openapi.json" if settings.prt_openapi_enabled else None

    app = FastAPI(
        title="PriceTracker API",
        version="0.1.0",
        description=(
            "API de PriceTracker — observatoire crowdsourcé de l'inflation "
            "consommateur (France). Vérifie les JWT Firebase. "
            "Tous les endpoints `/observatoire/*`, `/products/*`, `/indices/national`, "
            "`/indices/regional/*`, `/stats/*` sont publics ; les autres exigent "
            "un Bearer JWT Firebase."
        ),
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # CORS — `*` désactive obligatoirement allow_credentials (Bearer Auth sans cookie).
    # À durcir Phase 10 quand le frontend aura un domaine fixe.
    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False if "*" in origins else True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(tickets.router)
    app.include_router(indices.router)
    app.include_router(observatoire.router)
    app.include_router(products.router)
    app.include_router(stats.router)
    app.include_router(users.router)

    return app


app = _build_app()
