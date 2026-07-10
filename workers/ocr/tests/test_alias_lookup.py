"""Integration tests — EAN resolution via product_aliases (testcontainers).

Exercises the SHARED matcher (`pricetracker_matching.alias_lookup.resolve_line_eans`)
against a real Postgres seeded with a small product_aliases corpus, then proves
the tier-1 write path (`pg.upsert_prix_extraits`) persists the filled fields.
The tier-2 worker calls the exact same function at the same hook; its parity is
covered by workers/ocr-llm/tests/test_alias_lookup.py.

Covered: exact hit (catalogue), exact hit (user-validation), source priority,
enseigne discordante, plain miss, null-EAN alias, normaliser symmetry (accents
+ case + punctuation).
"""

from __future__ import annotations

import uuid

import pytest
from pricetracker_matching import alias_lookup
from testcontainers.postgres import PostgresContainer

from pricetracker_ocr import pg
from pricetracker_ocr.config import Settings

DDL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (id uuid PRIMARY KEY);

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
    # Same normalised key + enseigne from two sources → user-validation must win.
    ("YAOURT NATURE", "Carrefour", "catalogue", "3000000000001", 0.7, False),
    ("YAOURT NATURE", "Carrefour", "user-validation", "3000000000002", 1.0, True),
    # Different enseigne → must NOT match a Carrefour ticket.
    ("Beurre Doux", "Leclerc", "catalogue", "3111111111111", 0.7, False),
    # No EAN → cannot resolve anything.
    ("VRAC LEGUMES", "Carrefour", "catalogue", None, 0.7, False),
    # Accents + case + punctuation exercised by the shared normaliser.
    ("cafe ethiopie 250g", "Carrefour", "catalogue", "3222222222222", 0.7, False),
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


def _line(line_index: int, raw_text: str) -> dict:
    """A prix_extraits row exactly as mapper.map_prix_extraits_rows produces it."""
    return {
        "ticket_id": None,  # set per-test when persisting
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


async def _resolve(pool, enseigne: str, raw_texts: list[str]):
    rows = [_line(i, t) for i, t in enumerate(raw_texts)]
    stats = await alias_lookup.resolve_line_eans(pool, enseigne, rows)
    return rows, stats


@pytest.mark.integration
async def test_exact_hit_catalogue(pool):
    rows, _ = await _resolve(pool, "CARREFOUR MARKET", ["PAIN COMPLET"])
    row = rows[0]
    assert row["ean"] == "3270190123456"
    assert row["match_method"] == "alias-catalogue"
    assert row["match_confidence"] == pytest.approx(0.7)
    # Catalogue = suggestion (worker-derived, non validée) → reste à valider.
    assert row["needs_validation"] is True


@pytest.mark.integration
async def test_exact_hit_user_validation_clears_needs_validation(pool):
    rows, _ = await _resolve(pool, "CARREFOUR MARKET", ["lait uht"])
    row = rows[0]
    assert row["ean"] == "3560070111111"
    assert row["match_method"] == "alias-user"
    assert row["match_confidence"] == pytest.approx(1.0)
    assert row["needs_validation"] is False


@pytest.mark.integration
async def test_source_priority_user_beats_catalogue(pool):
    rows, _ = await _resolve(pool, "Carrefour", ["YAOURT NATURE"])
    row = rows[0]
    assert row["ean"] == "3000000000002"  # user-validation, not catalogue
    assert row["match_method"] == "alias-user"
    assert row["needs_validation"] is False


@pytest.mark.integration
async def test_enseigne_discordante_no_match(pool):
    # Beurre Doux only exists under Leclerc → a Carrefour ticket must not match.
    rows, _ = await _resolve(pool, "CARREFOUR MARKET", ["BEURRE DOUX"])
    row = rows[0]
    assert row["ean"] is None
    assert row["match_method"] == "none"
    assert row["needs_validation"] is True


@pytest.mark.integration
async def test_plain_miss_left_untouched(pool):
    rows, _ = await _resolve(pool, "CARREFOUR MARKET", ["PRODUIT INCONNU XYZ"])
    row = rows[0]
    assert row["ean"] is None
    assert row["match_method"] == "none"
    assert row["match_confidence"] is None
    assert row["needs_validation"] is True


@pytest.mark.integration
async def test_null_ean_alias_does_not_resolve(pool):
    rows, _ = await _resolve(pool, "CARREFOUR MARKET", ["VRAC LEGUMES"])
    assert rows[0]["ean"] is None
    assert rows[0]["match_method"] == "none"


@pytest.mark.integration
async def test_normaliser_symmetry_accents_case_punct(pool):
    rows, _ = await _resolve(pool, "CARREFOUR MARKET", ["CAFÉ ÉTHIOPIE 250G"])
    assert rows[0]["ean"] == "3222222222222"
    assert rows[0]["match_method"] == "alias-catalogue"


@pytest.mark.integration
async def test_stats_counters(pool):
    _rows, stats = await _resolve(
        pool,
        "CARREFOUR MARKET",
        [
            "PAIN COMPLET",        # catalogue
            "lait uht",            # user
            "YAOURT NATURE",       # user (priority)
            "BEURRE DOUX",         # miss (enseigne)
            "PRODUIT INCONNU XYZ", # miss
            "VRAC LEGUMES",        # miss (null ean)
            "CAFÉ ÉTHIOPIE 250G",  # catalogue
        ],
    )
    assert stats.n_lines == 7
    assert stats.n_resolved_user == 2
    assert stats.n_resolved_catalogue == 2
    assert stats.n_resolved_total == 4
    # user hits (2) clear needs_validation ; the other 5 lines still need it.
    assert stats.n_needs_validation == 5


@pytest.mark.integration
async def test_empty_rows_no_query(pool):
    stats = await alias_lookup.resolve_line_eans(pool, "CARREFOUR", [])
    assert stats.n_lines == 0
    assert stats.n_resolved_total == 0


class _RaisingPool:
    """Fake pool whose product_aliases read always fails (no container needed)."""

    async def fetch(self, *_args, **_kwargs):
        raise RuntimeError("product_aliases read failed")


async def test_read_failure_is_best_effort_no_raise():
    # A DB read failure must NEVER block ticket persistence: the matcher swallows
    # it, leaves lines unresolved, and returns truthful counters — no exception.
    rows = [_line(0, "PAIN COMPLET"), _line(1, "lait uht")]
    stats = await alias_lookup.resolve_line_eans(_RaisingPool(), "CARREFOUR MARKET", rows)
    for row in rows:
        assert row["ean"] is None
        assert row["match_method"] == "none"
        assert row["needs_validation"] is True
    assert stats.n_resolved_total == 0
    assert stats.n_needs_validation == 2


@pytest.mark.integration
async def test_end_to_end_upsert_persists_resolution(pool):
    """Tier-1 write path: resolved fields land in prix_extraits unchanged."""
    ticket_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (id) VALUES ($1::uuid)", user_id)
        await conn.execute(
            """
            INSERT INTO tickets (id, user_id, gcs_path, status, enseigne)
            VALUES ($1::uuid, $2::uuid, $3, 'ocr_processing', 'CARREFOUR MARKET')
            """,
            ticket_id, user_id, f"tickets/raw/{user_id}/{ticket_id}.jpg",
        )

    rows = [_line(0, "PAIN COMPLET"), _line(1, "lait uht"), _line(2, "INCONNU")]
    for r in rows:
        r["ticket_id"] = ticket_id
    await alias_lookup.resolve_line_eans(pool, "CARREFOUR MARKET", rows)
    await pg.upsert_prix_extraits(pool, rows)

    async with pool.acquire() as conn:
        persisted = {
            r["line_index"]: r
            for r in await conn.fetch(
                "SELECT line_index, ean, match_method, needs_validation "
                "FROM prix_extraits WHERE ticket_id = $1::uuid",
                ticket_id,
            )
        }
    assert persisted[0]["ean"] == "3270190123456"
    assert persisted[0]["match_method"] == "alias-catalogue"
    assert persisted[0]["needs_validation"] is True
    assert persisted[1]["ean"] == "3560070111111"
    assert persisted[1]["match_method"] == "alias-user"
    assert persisted[1]["needs_validation"] is False
    assert persisted[2]["ean"] is None
    assert persisted[2]["needs_validation"] is True
