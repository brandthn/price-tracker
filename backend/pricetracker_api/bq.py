"""Client BigQuery — wrappers observatoire / catalogue.

SDK BQ synchrone, expose via asyncio.to_thread dans les routers. Tolerant aux
tables vides/NULL : tables Gold pas encore remplies -> liste vide, pas de 500 ;
catalogue_produits peut avoir off_found=False (nom/marque/categorie NULL).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from google.cloud import bigquery

from .config import get_settings
from .logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_client() -> bigquery.Client:
    settings = get_settings()
    project = settings.google_cloud_project or None
    return bigquery.Client(project=project, location=settings.prt_bq_location)


def reset_client_cache() -> None:
    get_client.cache_clear()


def qualified(dataset: str, table: str) -> str:
    settings = get_settings()
    project = settings.google_cloud_project
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT not set.")
    return f"`{project}.{dataset}.{table}`"


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    # Row BQ pas serializable par FastAPI ; DATE/DATETIME -> isoformat pour pydantic
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row.items())
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return out


def query_dicts(
    sql: str,
    *,
    params: list[bigquery.ScalarQueryParameter] | None = None,
) -> list[dict[str, Any]]:
    # 0 row -> [] ; exception (table absente, denied) remonte au router
    client = get_client()
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    job = client.query(sql, job_config=job_config)
    return rows_to_dicts(job.result())


# departement FR depuis le code postal Silver. cas speciaux : Corse (20xxx -> 2A/2B)
# et DOM (97x/98x sur 3 chiffres). utilise par les requetes regionales.
DEPT_FROM_POSTCODE_SQL = """
    CASE
      WHEN postcode LIKE '97%' OR postcode LIKE '98%' THEN SUBSTR(postcode, 1, 3)
      WHEN postcode LIKE '20%' THEN
        IF(SAFE_CAST(SUBSTR(postcode, 1, 3) AS INT64) < 202, '2A', '2B')
      ELSE SUBSTR(postcode, 1, 2)
    END
"""


def query_dicts_safe(
    sql: str,
    *,
    params: list[bigquery.ScalarQueryParameter] | None = None,
    context: str,
) -> list[dict[str, Any]]:
    # log + [] si la table n'existe pas encore ou est vide. pour les endpoints
    # observatoire publics qui doivent rester up sans le worker indices.
    try:
        return query_dicts(sql, params=params)
    except Exception as exc:
        logger.warning(
            "bq_query_failed_returning_empty",
            context=context,
            error=str(exc),
        )
        return []
