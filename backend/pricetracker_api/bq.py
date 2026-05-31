"""Client BigQuery — wrappers fins autour des queries observatoire / catalogue.

Les méthodes sont synchrones (le SDK BQ l'est) ; on les expose dans les
routers via `asyncio.to_thread(...)` pour ne pas bloquer l'event loop.

Tolérant aux tables vides / NULL :
- Les workers Indices/Alertes (Phase 9) n'ont pas encore rempli les tables
  Gold → on renvoie une liste vide plutôt qu'une 500.
- Le worker OFF est rate-limité (15 req/min) → `catalogue_produits` peut
  contenir des EAN avec `off_found=False` (nom, marque, catégorie = NULL).
  Les `Product` Pydantic acceptent ces NULL explicitement.
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
    """Convertit un RowIterator BQ en liste de dicts JSON-serializables.

    BigQuery renvoie des `Row` qui se comportent comme des dicts mais ne
    sont pas serializables par FastAPI. On convertit les DATE/DATETIME en
    isoformat pour pydantic.
    """
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
    """Exécute une query et renvoie les rows en list[dict].

    Tolère les tables vides : 0 row → []. Une exception (table absente,
    permission denied) remonte — le router décidera de la mapper en 200
    avec liste vide ou en 500.
    """
    client = get_client()
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    job = client.query(sql, job_config=job_config)
    return rows_to_dicts(job.result())


def query_dicts_safe(
    sql: str,
    *,
    params: list[bigquery.ScalarQueryParameter] | None = None,
    context: str,
) -> list[dict[str, Any]]:
    """Variante 'safe' : log l'erreur et renvoie [] si la table n'existe pas
    encore (Phase 9 pas livrée) ou est vide.

    À utiliser pour les endpoints observatoire publics qui doivent rester
    up même si le worker indices n'a pas encore tourné.
    """
    try:
        return query_dicts(sql, params=params)
    except Exception as exc:
        logger.warning(
            "bq_query_failed_returning_empty",
            context=context,
            error=str(exc),
        )
        return []
