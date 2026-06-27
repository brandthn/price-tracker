"""Cloud SQL access pour le worker OCR tier-2.

Contrat minimal : on reçoit un ticket, on relit son image + son extraction
précédente, on ré-écrit `prix_extraits` et on incrémente `ocr_attempts`. Pas de
machine à états (pas de claim) : le backend est le gatekeeper (il ne publie que
si `ocr_attempts < max`), et un doublon de livraison Pub/Sub ne fait que ré-écrire
le même résultat — inoffensif.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from .config import Settings


def _build_dsn(settings: Settings) -> str:
    return (
        f"postgresql://{settings.prt_pg_user}:{settings.prt_pg_password}"
        f"@{settings.prt_pg_host}:{settings.prt_pg_port}/{settings.prt_pg_db}"
    )


async def create_pool(settings: Settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=_build_dsn(settings),
        min_size=1,
        max_size=settings.prt_pg_pool_size,
    )


async def get_ticket(pool: asyncpg.Pool, ticket_id: str) -> asyncpg.Record | None:
    """gcs_path (image à OCR) + extraction précédente (contexte prompt correctif)."""
    return await pool.fetchrow(
        """
        SELECT gcs_path, ocr_attempts, enseigne, date_ticket
        FROM tickets
        WHERE id = $1::uuid
        """,
        ticket_id,
    )


async def fetch_prix_extraits(pool: asyncpg.Pool, ticket_id: str) -> list[asyncpg.Record]:
    """Extraction précédente (pour injecter dans le prompt correctif)."""
    return await pool.fetch(
        """
        SELECT line_index, raw_text, unit_price, quantity
        FROM prix_extraits
        WHERE ticket_id = $1::uuid
        ORDER BY line_index
        """,
        ticket_id,
    )


async def delete_prix_extraits(pool: asyncpg.Pool, ticket_id: str) -> None:
    """Clean slate : la tier-2 peut renvoyer un nombre de lignes différent."""
    await pool.execute(
        "DELETE FROM prix_extraits WHERE ticket_id = $1::uuid", ticket_id
    )


async def set_ticket_done(
    pool: asyncpg.Pool, ticket_id: str, fields: dict[str, Any], model: str
) -> None:
    """Écrit le résultat OCR tier-2 : champs + ocr_model + bump ocr_attempts.

    Le ticket reste `ocr_done` (il l'était déjà). Pas de flip de statut : en cas
    d'échec tier-2, on laisse le résultat tier-1 intact côté appelant.
    """
    await pool.execute(
        """
        UPDATE tickets
        SET enseigne        = $2,
            date_ticket     = $3,
            total_eur       = $4,
            ocr_confidence  = $5,
            ocr_engine      = $6,
            ocr_duration_ms = $7,
            ocr_model       = $8,
            ocr_attempts    = ocr_attempts + 1,
            updated_at      = now()
        WHERE id = $1::uuid
        """,
        ticket_id,
        fields.get("enseigne"),
        fields.get("ticket_date"),
        fields.get("total_amount"),
        fields.get("ocr_confidence"),
        fields.get("ocr_engine"),
        fields.get("ocr_duration_ms"),
        model,
    )


_INSERT_SQL = """
INSERT INTO prix_extraits (
    ticket_id, line_index, raw_text, quantity, unit_price, line_total,
    ean, match_method, match_confidence, needs_validation, validated_by_user
)
VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11
)
ON CONFLICT (ticket_id, line_index)
DO UPDATE SET
    raw_text         = EXCLUDED.raw_text,
    quantity         = EXCLUDED.quantity,
    unit_price       = EXCLUDED.unit_price,
    line_total       = EXCLUDED.line_total,
    ean              = EXCLUDED.ean,
    match_method     = EXCLUDED.match_method,
    match_confidence = EXCLUDED.match_confidence,
    needs_validation = EXCLUDED.needs_validation
"""


async def upsert_prix_extraits(pool: asyncpg.Pool, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    records = [
        (
            row["ticket_id"],
            row["line_index"],
            row["raw_text"],
            row["quantity"],
            row["unit_price"],
            row["line_total"],
            row["ean"],
            row["match_method"],
            row["match_confidence"],
            row["needs_validation"],
            row["validated_by_user"],
        )
        for row in rows
    ]
    await pool.executemany(_INSERT_SQL, records)
