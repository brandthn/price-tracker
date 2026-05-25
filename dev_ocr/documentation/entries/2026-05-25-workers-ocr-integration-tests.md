### Entry 10 — 2026-05-25 (UTC+2)

**Scope:** Verify `workers/ocr/` Postgres integration tests with Docker (testcontainers) and fix shared-container DDL setup.

#### Context

Entry 9 added `workers/ocr/tests/test_pg.py` with four tests marked `@pytest.mark.integration`, using `PostgresContainer("pgvector/pgvector:pg15")`. Those tests could not run until Docker Desktop was available.

#### Problem on first run

With a **module-scoped** Postgres container and a **function-scoped** `pool` fixture that executed the full `DDL` on every test:

- `test_set_ticket_processing_returns_true` passed (schema created once).
- The next three tests failed at fixture setup with `asyncpg.exceptions.DuplicateObjectError: type "ticket_status" already exists`.

#### Fix

Made bootstrap SQL idempotent in `workers/ocr/tests/test_pg.py`:

- `ticket_status` enum: `DO $$ … EXCEPTION WHEN duplicate_object THEN NULL; END $$`
- Tables: `CREATE TABLE IF NOT EXISTS` for `users`, `tickets`, `prix_extraits`

No change to production `pg.py` — test-only.

#### Test results (Docker running)

```text
pytest -m integration   → 4 passed in ~20s
pytest                  → 18 passed in ~25s (14 unit + 4 integration)
```

| Integration test | Asserts |
|------------------|---------|
| `test_set_ticket_processing_returns_true` | `pending` → `ocr_processing`, one row updated |
| `test_set_ticket_processing_idempotent` | Second call returns `False` (0 rows) |
| `test_upsert_prix_extraits_no_duplicate` | `ON CONFLICT` updates `raw_text`, count stays 1 |
| `test_set_ticket_failed` | `status='ocr_failed'`, `error_message` set |

#### How to run

```powershell
cd workers/ocr
uv sync
uv run pytest -m integration -v    # Postgres via testcontainers (Docker required)
uv run pytest -v                   # full suite
```

#### References

- Worker implementation: Entry 9 in this file
- Contract DDL: [`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md) §6

---
