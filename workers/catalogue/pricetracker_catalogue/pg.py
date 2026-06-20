"""Accès Cloud SQL (PostgreSQL) — même pattern que workers/off/pg.py.

Gère :
- Pool de connexions via psycopg2
- Schéma (idempotent)
- Upserts des produits matchés
- Table de progression pour reprise sur interruption
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values

from .config import Settings
from .logging import get_logger

logger = get_logger(__name__)

_pool: pool.SimpleConnectionPool | None = None


def _build_dsn(settings: Settings) -> str:
    db_host = os.environ.get("PRT_DB_HOST", "127.0.0.1")
    db_port = os.environ.get("PRT_DB_PORT", "5433")
    db_user = os.environ.get("PRT_DB_USER", settings.prt_db_user)

    logger.info("pg_env_check", host=db_host, user=db_user)

    if db_host.startswith("/cloudsql"):
        return (
            f"host={db_host} "
            f"dbname={settings.prt_db_name} "
            f"user={db_user} "
            f"password={settings.prt_db_password}"
        )
    return (
        f"host={db_host} port={db_port} "
        f"dbname={settings.prt_db_name} "
        f"user={db_user} "
        f"password={settings.prt_db_password}"
    )


def init_pool(settings: Settings) -> None:
    global _pool
    dsn = _build_dsn(settings)
    _pool = pool.SimpleConnectionPool(minconn=1, maxconn=5, dsn=dsn)
    logger.info("pg_pool_ready")


@contextmanager
def get_conn(settings: Settings):
    global _pool
    if _pool is None:
        init_pool(settings)
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ─────────────────────────────────────────────────────────────────────────────
# SCHÉMA
# ─────────────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogue_products (
    ean         TEXT PRIMARY KEY,
    nom         TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS catalogue_labels (
    id                  SERIAL PRIMARY KEY,
    ean                 TEXT NOT NULL REFERENCES catalogue_products(ean),
    libelle_original    TEXT NOT NULL,
    libelle_normalise   TEXT NOT NULL,
    enseigne            TEXT,
    prix                NUMERIC(10, 3),
    proof_id            INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ean, libelle_normalise, enseigne)
);

CREATE TABLE IF NOT EXISTS catalogue_receipts (
    proof_id                INTEGER PRIMARY KEY,
    enseigne                TEXT,
    date_ticket             DATE,
    pays                    TEXT,
    nb_produits_dataset     INTEGER,
    nb_produits_matches     INTEGER,
    couverture              NUMERIC(4, 3),
    traite_le               TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS catalogue_progression (
    proof_id    INTEGER PRIMARY KEY,
    statut      TEXT NOT NULL,   -- 'ok' | 'erreur' | 'ignore'
    detail      TEXT,
    traite_le   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cat_labels_ean      ON catalogue_labels(ean);
CREATE INDEX IF NOT EXISTS idx_cat_labels_enseigne ON catalogue_labels(enseigne);
"""


def ensure_schema(settings: Settings) -> None:
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
    logger.info("pg_schema_ready")


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESSION
# ─────────────────────────────────────────────────────────────────────────────

def get_processed_ids(settings: Settings) -> set[int]:
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT proof_id FROM catalogue_progression")
            return {row[0] for row in cur.fetchall()}


def mark_processed(settings: Settings, proof_id: int, statut: str, detail: str = "") -> None:
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalogue_progression (proof_id, statut, detail)
                VALUES (%s, %s, %s)
                ON CONFLICT (proof_id) DO UPDATE
                SET statut = EXCLUDED.statut,
                    detail = EXCLUDED.detail,
                    traite_le = NOW()
                """,
                (proof_id, statut, detail),
            )


# ─────────────────────────────────────────────────────────────────────────────
# INSERTIONS
# ─────────────────────────────────────────────────────────────────────────────

def upsert_receipt(
    settings: Settings,
    *,
    proof_id: int,
    enseigne: str,
    date_ticket,
    pays: str,
    nb_produits_dataset: int,
    nb_produits_matches: int,
) -> None:
    couverture = (
        nb_produits_matches / nb_produits_dataset if nb_produits_dataset > 0 else 0
    )
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalogue_receipts
                    (proof_id, enseigne, date_ticket, pays,
                     nb_produits_dataset, nb_produits_matches, couverture)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proof_id) DO UPDATE SET
                    nb_produits_dataset = EXCLUDED.nb_produits_dataset,
                    nb_produits_matches = EXCLUDED.nb_produits_matches,
                    couverture          = EXCLUDED.couverture,
                    traite_le           = NOW()
                """,
                (
                    proof_id, enseigne, date_ticket, pays,
                    nb_produits_dataset, nb_produits_matches,
                    round(couverture, 3),
                ),
            )


def upsert_matches(settings: Settings, matches: list[dict]) -> None:
    """
    Insère les produits matchés.
    Chaque dict : ean, nom_canonique, libelle_original, libelle_normalise,
                  enseigne, prix, proof_id.
    """
    if not matches:
        return

    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            # 1. products
            execute_values(
                cur,
                """
                INSERT INTO catalogue_products (ean, nom)
                VALUES %s
                ON CONFLICT (ean) DO UPDATE SET
                    nom        = COALESCE(EXCLUDED.nom, catalogue_products.nom),
                    updated_at = NOW()
                """,
                [(m["ean"], m.get("nom_canonique", "")) for m in matches],
            )
            # 2. labels
            execute_values(
                cur,
                """
                INSERT INTO catalogue_labels
                    (ean, libelle_original, libelle_normalise, enseigne, prix, proof_id)
                VALUES %s
                ON CONFLICT (ean, libelle_normalise, enseigne) DO UPDATE SET
                    prix     = EXCLUDED.prix,
                    proof_id = EXCLUDED.proof_id
                """,
                [
                    (
                        m["ean"],
                        m["libelle_original"],
                        m["libelle_normalise"],
                        m.get("enseigne", ""),
                        m.get("prix"),
                        m.get("proof_id"),
                    )
                    for m in matches
                ],
            )
