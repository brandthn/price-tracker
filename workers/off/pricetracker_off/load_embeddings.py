"""Load embeddings into Cloud SQL only."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from .config import get_settings
from .load_artifact import read_artifact
from .logging import configure_logging, get_logger
from .pg import open_pool, update_embeddings

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


async def load(gcs_uri: str) -> dict[str, object]:
    t0 = time.monotonic()
    settings = get_settings()

    products, embeddings = await asyncio.to_thread(read_artifact, gcs_uri)
    n_with_emb = sum(e is not None for e in embeddings)
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
        result = await update_embeddings(pool, products=products, embeddings=embeddings)
    finally:
        await pool.close()

    duration_s = round(time.monotonic() - t0, 2)
    out = {
        "rows": len(products),
        "with_embedding": n_with_emb,
        "candidates": result["candidates"],
        "updated": result["updated"],
        "duration_s": duration_s,
    }
    logger.info("reembed_done", **out)
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
