"""Cloud SQL access for tickets and prix_extraits.

Noms de colonnes utilisés = schéma prod (migration 0001 + 0002) :
  tickets  : date_ticket, total_eur, ocr_error, ocr_engine, ocr_duration_ms
  prix_extraits : unit_price, line_total, match_method
  + contrainte UNIQUE(ticket_id, line_index) + DEFAULT gen_random_uuid() sur id
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


async def set_ticket_processing(pool: asyncpg.Pool, ticket_id: str) -> bool:
    """Set status to 'ocr_processing' si encore pending/uploaded. Retourne True si claimé."""
    result = await pool.execute(
        """
        UPDATE tickets
        SET status = 'ocr_processing', updated_at = now()
        WHERE id = $1::uuid AND status IN ('pending', 'uploaded')
        """,
        ticket_id,
    )
    return result.endswith("1")


async def set_ticket_done(pool: asyncpg.Pool, ticket_id: str, fields: dict[str, Any]) -> None:
    """Mise à jour tickets au succès OCR. Les clés de `fields` sont les noms
    Python du mapper (ticket_date, total_amount) ; on les écrit dans les
    colonnes DB réelles (date_ticket, total_eur, ocr_engine, ocr_duration_ms).
    """
    await pool.execute(
        """
        UPDATE tickets
        SET status         = 'ocr_done',
            enseigne       = $2,
            date_ticket    = $3,
            total_eur      = $4,
            ocr_confidence = $5,
            ocr_engine     = $6,
            ocr_duration_ms = $7,
            updated_at     = now()
        WHERE id = $1::uuid
        """,
        ticket_id,
        fields.get("enseigne"),
        fields.get("ticket_date"),
        fields.get("total_amount"),
        fields.get("ocr_confidence"),
        fields.get("ocr_engine"),
        fields.get("ocr_duration_ms"),
    )


async def set_ticket_failed(
    pool: asyncpg.Pool, ticket_id: str, error_message: str
) -> None:
    await pool.execute(
        """
        UPDATE tickets
        SET status    = 'ocr_failed',
            ocr_error = $2,
            updated_at = now()
        WHERE id = $1::uuid
        """,
        ticket_id,
        error_message,
    )


_UPSERT_SQL = """
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
    await pool.executemany(_UPSERT_SQL, records)
