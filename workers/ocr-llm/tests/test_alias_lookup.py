"""Parité de la résolution EAN entre le tier-2 et le tier-1 (testcontainers).

Le tier-2 appelle le même matcher au même endroit du flux. On vérifie que les
résolutions sont identiques, et que l'écriture atomique du tier-2 reporte bien les
champs remplis sans les abîmer.
"""

from __future__ import annotations

import uuid

import pytest
from pricetracker_matching import alias_lookup
from testcontainers.postgres import PostgresContainer

from pricetracker_ocr_llm import pg
from pricetracker_ocr_llm.config import Settings

DDL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (id uuid PRIMARY KEY);

CREATE TABLE IF NOT EXISTS tickets (
  id              uuid PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES users(id),
  gcs_path        text NOT NULL UNIQUE,
  status          text NOT NULL DEFAULT 'ocr_done',
  enseigne        text,
  date_ticket     date,
  total_eur       numeric(10,2),
  ocr_confidence  real,
  ocr_engine      text,
  ocr_duration_ms integer,
  ocr_model       text,
  ocr_attempts    integer NOT NULL DEFAULT 1,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prix_extraits (
  id               uuid NOT NULL DEFAULT gen_random_uuid(),
  ticket_id        uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  line_index       smallint NOT NULL,
  raw_text         text NOT NULL,
  quantity         numeric(8,3),
  unit_price       numeric(10,2),
  line_total       numeric(10,2),
  ean              text,
  match_method     text,
  match_confidence real,
  needs_validation boolean NOT NULL DEFAULT true,
  validated_by_user boolean NOT NULL DEFAULT false,
  PRIMARY KEY (id),
  UNIQUE (ticket_id, line_index)
);

CREATE TABLE IF NOT EXISTS product_aliases (
  raw_text          text NOT NULL,
  enseigne          text NOT NULL,
  source            text NOT NULL,
  ean               text,
  produit_nom       text,
  confidence        real,
  validated_by_user boolean NOT NULL DEFAULT false,
  matched_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (raw_text, enseigne, source)
);
"""

# (raw_text, enseigne, source, ean, confidence, validated_by_user)
_ALIASES = [
    ("Pain Complet", "Carrefour", "catalogue", "3270190123456", 0.7, False),
    ("LAIT UHT", "Carrefour Market", "user-validation", "3560070111111", 1.0, True),
    ("YAOURT NATURE", "Carrefour", "catalogue", "3000000000001", 0.7, False),
    ("YAOURT NATURE", "Carrefour", "user-validation", "3000000000002", 1.0, True),
    ("Beurre Doux", "Leclerc", "catalogue", "3111111111111", 0.7, False),
]


@pytest.fixture(scope="module")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg15") as postgres:
        yield postgres


@pytest.fixture
async def pool(pg_container):
    settings = Settings(
        prt_pg_host=pg_container.get_container_host_ip(),
        prt_pg_port=int(pg_container.get_exposed_port(5432)),
        prt_pg_db=pg_container.dbname,
        prt_pg_user=pg_container.username,
        prt_pg_password=pg_container.password,
        prt_pg_pool_size=2,
    )
    pool = await pg.create_pool(settings)
    async with pool.acquire() as conn:
        await conn.execute(DDL)
        await conn.execute("TRUNCATE product_aliases")
        for raw_text, enseigne, source, ean, confidence, validated in _ALIASES:
            await conn.execute(
                """
                INSERT INTO product_aliases
                    (raw_text, enseigne, source, ean, confidence, validated_by_user)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                raw_text, enseigne, source, ean, confidence, validated,
            )
    yield pool
    await pool.close()


def _line(line_index: int, raw_text: str, ticket_id: str) -> dict:
    return {
        "ticket_id": ticket_id,
        "line_index": line_index,
        "raw_text": raw_text,
        "quantity": 1.0,
        "unit_price": 1.0,
        "line_total": 1.0,
        "ean": None,
        "match_method": "none",
        "match_confidence": None,
        "needs_validation": True,
        "validated_by_user": False,
    }


class _RaisingPool:
    """Fake pool whose product_aliases read always fails (no container needed)."""

    async def fetch(self, *_args, **_kwargs):
        raise RuntimeError("product_aliases read failed")


async def test_read_failure_is_best_effort_no_raise():
    # Parity with tier-1: a read failure never blocks tier-2 persistence either.
    rows = [_line(0, "PAIN COMPLET", "t"), _line(1, "lait uht", "t")]
    stats = await alias_lookup.resolve_line_eans(_RaisingPool(), "CARREFOUR MARKET", rows)
    for row in rows:
        assert row["ean"] is None
        assert row["match_method"] == "none"
        assert row["needs_validation"] is True
    assert stats.n_resolved_total == 0
    assert stats.n_needs_validation == 2


@pytest.mark.integration
async def test_resolution_outcomes_identical_to_tier1(pool):
    rows = [
        _line(0, "PAIN COMPLET", "t"),
        _line(1, "lait uht", "t"),
        _line(2, "YAOURT NATURE", "t"),
        _line(3, "BEURRE DOUX", "t"),   # Leclerc → miss
        _line(4, "INCONNU", "t"),
    ]
    stats = await alias_lookup.resolve_line_eans(pool, "CARREFOUR MARKET", rows)

    assert rows[0]["match_method"] == "alias-catalogue"
    assert rows[0]["ean"] == "3270190123456"
    assert rows[0]["needs_validation"] is True

    assert rows[1]["match_method"] == "alias-user"
    assert rows[1]["needs_validation"] is False

    assert rows[2]["ean"] == "3000000000002"  # user beats catalogue
    assert rows[2]["needs_validation"] is False

    assert rows[3]["ean"] is None and rows[3]["match_method"] == "none"
    assert rows[4]["ean"] is None and rows[4]["match_method"] == "none"

    assert stats.n_resolved_user == 2
    assert stats.n_resolved_catalogue == 1
    assert stats.n_needs_validation == 3


@pytest.mark.integration
async def test_atomic_persist_carries_resolution(pool):
    ticket_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (id) VALUES ($1::uuid)", user_id)
        await conn.execute(
            """
            INSERT INTO tickets (id, user_id, gcs_path, status, enseigne, ocr_attempts)
            VALUES ($1::uuid, $2::uuid, $3, 'ocr_done', 'CARREFOUR MARKET', 1)
            """,
            ticket_id, user_id, f"tickets/raw/{user_id}/{ticket_id}.jpg",
        )

    rows = [
        _line(0, "PAIN COMPLET", ticket_id),
        _line(1, "lait uht", ticket_id),
        _line(2, "INCONNU", ticket_id),
    ]
    await alias_lookup.resolve_line_eans(pool, "CARREFOUR MARKET", rows)

    fields = {
        "enseigne": "CARREFOUR MARKET",
        "ticket_date": None,
        "total_amount": None,
        "ocr_confidence": 1.0,
        "ocr_engine": "groq",
        "ocr_duration_ms": 1234,
    }
    await pg.persist_tier2_result(pool, ticket_id, fields, "llama-4-scout", rows)

    async with pool.acquire() as conn:
        persisted = {
            r["line_index"]: r
            for r in await conn.fetch(
                "SELECT line_index, ean, match_method, needs_validation "
                "FROM prix_extraits WHERE ticket_id = $1::uuid",
                ticket_id,
            )
        }
        attempts = await conn.fetchval(
            "SELECT ocr_attempts FROM tickets WHERE id = $1::uuid", ticket_id
        )
    assert persisted[0]["ean"] == "3270190123456"
    assert persisted[0]["match_method"] == "alias-catalogue"
    assert persisted[0]["needs_validation"] is True
    assert persisted[1]["ean"] == "3560070111111"
    assert persisted[1]["match_method"] == "alias-user"
    assert persisted[1]["needs_validation"] is False
    assert persisted[2]["ean"] is None
    assert attempts == 2  # bumped by the atomic persist
