"""Cloud SQL access des workers OCR par backend.

Copie de workers/ocr-llm/pricetracker_ocr_llm/pg.py (``persist_tier2_result``
renommé ``persist_result``, sans ``fetch_prix_extraits`` — le prompt correctif
est propre au tier-2 Gemini). Contrat identique : on reçoit un ticket, on
ré-écrit `prix_extraits` et on incrémente `ocr_attempts` de façon ATOMIQUE.
Pas de machine à états : un doublon de livraison Pub/Sub ne fait que ré-écrire
le même résultat — inoffensif.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from .config import BaseWorkerSettings


def _build_dsn(settings: BaseWorkerSettings) -> str:
    return (
        f"postgresql://{settings.prt_pg_user}:{settings.prt_pg_password}"
        f"@{settings.prt_pg_host}:{settings.prt_pg_port}/{settings.prt_pg_db}"
    )


async def create_pool(settings: BaseWorkerSettings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=_build_dsn(settings),
        min_size=1,
        max_size=settings.prt_pg_pool_size,
    )


async def get_ticket(pool: asyncpg.Pool, ticket_id: str) -> asyncpg.Record | None:
    """gcs_path (image à OCR) + contexte du ticket."""
    return await pool.fetchrow(
        """
        SELECT gcs_path, ocr_attempts, enseigne, date_ticket
        FROM tickets
        WHERE id = $1::uuid
        """,
        ticket_id,
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


async def persist_result(
    pool: asyncpg.Pool,
    ticket_id: str,
    fields: dict[str, Any],
    model: str,
    rows: list[dict[str, Any]],
) -> None:
    """Persiste le résultat OCR de façon ATOMIQUE.

    Tout dans UNE transaction, sur UNE connexion, dans cet ordre :
      1. DELETE des anciennes lignes (clean slate : une nouvelle passe peut en
         renvoyer un nombre différent).
      2. INSERT des nouvelles lignes.
      3. UPDATE tickets : champs + ocr_model + bump `ocr_attempts` (EN DERNIER).

    Pourquoi atomique + bump en dernier :
    - Le frontend poll `ocr_attempts > baseline` pour détecter la fin de
      l'analyse. L'observateur externe ne voit jamais d'état partiel : soit
      l'ancien résultat complet, soit le nouveau.
    - En cas d'échec d'une étape, la transaction rollback : le résultat
      précédent reste INTACT.

    Le statut n'est pas touché.
    """
    insert_records = [
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

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM prix_extraits WHERE ticket_id = $1::uuid", ticket_id
            )
            if insert_records:
                await conn.executemany(_INSERT_SQL, insert_records)
            await conn.execute(
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
