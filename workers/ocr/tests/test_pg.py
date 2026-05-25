"""Integration tests for Cloud SQL helpers (testcontainers).

DDL = miroir du schéma prod après migration 0002 :
  - tickets : colonnes date_ticket, total_eur, ocr_error, ocr_engine, ocr_duration_ms
  - prix_extraits : id UUID DEFAULT gen_random_uuid() + UNIQUE(ticket_id, line_index)
                   + colonnes unit_price, line_total, match_method
"""

from __future__ import annotations

import uuid

import pytest
from testcontainers.postgres import PostgresContainer

from pricetracker_ocr import pg
from pricetracker_ocr.config import Settings

DDL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tickets (
  id              uuid PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES users(id),
  gcs_path        text NOT NULL UNIQUE,
  status          text NOT NULL DEFAULT 'pending',
  enseigne        text,
  date_ticket     date,
  total_eur       numeric(10,2),
  ocr_confidence  real,
  ocr_engine      text,
  ocr_duration_ms integer,
  ocr_error       text,
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
"""


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
    yield pool
    await pool.close()


async def _seed_ticket(pool, ticket_id: str, status: str = "pending") -> None:
    user_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (id) VALUES ($1::uuid)", user_id)
        await conn.execute(
            """
            INSERT INTO tickets (id, user_id, gcs_path, status)
            VALUES ($1::uuid, $2::uuid, $3, $4)
            """,
            ticket_id,
            user_id,
            f"tickets/raw/{user_id}/{ticket_id}.jpg",
            status,
        )


@pytest.mark.integration
async def test_set_ticket_processing_returns_true(pool):
    ticket_id = str(uuid.uuid4())
    await _seed_ticket(pool, ticket_id, "pending")
    assert await pg.set_ticket_processing(pool, ticket_id) is True


@pytest.mark.integration
async def test_set_ticket_processing_idempotent(pool):
    ticket_id = str(uuid.uuid4())
    await _seed_ticket(pool, ticket_id, "pending")
    assert await pg.set_ticket_processing(pool, ticket_id) is True
    assert await pg.set_ticket_processing(pool, ticket_id) is False


@pytest.mark.integration
async def test_upsert_prix_extraits_no_duplicate(pool):
    ticket_id = str(uuid.uuid4())
    await _seed_ticket(pool, ticket_id, "ocr_processing")
    rows = [
        {
            "ticket_id": ticket_id,
            "line_index": 0,
            "raw_text": "PAIN",
            "quantity": 1.0,
            "unit_price": 1.2,
            "line_total": 1.2,
            "ean": None,
            "match_method": "none",
            "match_confidence": None,
            "needs_validation": True,
            "validated_by_user": False,
        }
    ]
    await pg.upsert_prix_extraits(pool, rows)
    rows[0]["raw_text"] = "PAIN BIO"
    await pg.upsert_prix_extraits(pool, rows)

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM prix_extraits WHERE ticket_id = $1::uuid",
            ticket_id,
        )
    assert count == 1
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT raw_text FROM prix_extraits WHERE ticket_id = $1::uuid AND line_index = 0",
            ticket_id,
        )
    assert raw == "PAIN BIO"


@pytest.mark.integration
async def test_set_ticket_failed(pool):
    ticket_id = str(uuid.uuid4())
    await _seed_ticket(pool, ticket_id, "ocr_processing")
    await pg.set_ticket_failed(pool, ticket_id, "corrupt image")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, ocr_error FROM tickets WHERE id = $1::uuid",
            ticket_id,
        )
    assert row["status"] == "ocr_failed"
    assert row["ocr_error"] == "corrupt image"
