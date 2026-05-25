## Version 0.1.5 (unreleased)

### Entry 9 — 2026-05-25 (UTC+2)

**Scope:** Production Cloud Run worker `workers/ocr/` (`prt-prod-worker-ocr`) — Pub/Sub push shell around `receipt_ocr` with **Groq VLM** as default engine. EAN matching / Vertex embeddings explicitly **not** implemented (Phase 8 placeholder).

#### Motivation

`receipt_ocr` in `dev_ocr/` already extracts structured tickets via `extract_receipt()` (Groq: `RECEIPT_OCR_BACKEND=vlm`, `RECEIPT_VLM_MODEL=groq-llama4-scout`, `RECEIPT_VLM_MODE=json`). The monorepo needed an event-driven worker matching [`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md): GCS bronze download → OCR → Cloud SQL, without rewriting the OCR package.

#### What was implemented

| Component | Path | Role |
|-----------|------|------|
| FastAPI app | `workers/ocr/pricetracker_ocr/main.py` | `GET /healthz`, `POST /push` (Pub/Sub pipeline) |
| Pub/Sub parsing | `pubsub.py` | Decode push envelope → `(bucket, object_path)`; `extract_ticket_id` / `extract_user_id` |
| GCS | `gcs.py` | `download_image()` (ADC, 10 MB max) |
| OCR adapter | `ocr.py` | Temp file → `extract_receipt()`; engine map: `groq` / `paddleocr` / `tesseract` |
| SQL mapper | `mapper.py` | Canonical dict → `tickets` + `prix_extraits` columns |
| Cloud SQL | `pg.py` | asyncpg pool, idempotent status updates, `prix_extraits` UPSERT |
| Config | `config.py` | `PRT_*` pydantic-settings, `@lru_cache` `get_settings()` |
| Auth / logs | `auth.py`, `logging.py` | Copied verbatim from `workers/off/` |
| Packaging | `pyproject.toml`, `Dockerfile`, `cloudbuild.yaml` | Installs `receipt-ocr` from `dev_ocr/` at image build |
| LLM reference | `workers/ocr/dev_ocr_codebase_reference_for_llm.md` | Standalone doc for downstream prompts |
| Tests | `workers/ocr/tests/` | pubsub, mapper, push contract (14 unit); pg integration (testcontainers, needs Docker) |

**Not created (per contract / prompt):** `matcher.py`, `vertex.py`, `parser/`, `product_aliases` INSERT.

#### End-to-end flow (happy path)

```text
POST /push (OIDC)
  → parse_pubsub_envelope → GCS path + ticket_id (UUID from filename)
  → UPDATE tickets status='ocr_processing' (only if pending/uploaded)
  → download_image(bronze bucket)
  → run_ocr(bytes, PRT_OCR_ENGINE)  [default groq → receipt_ocr VLM JSON]
  → map_ticket_fields + map_prix_extraits_rows
  → UPDATE tickets status='ocr_done'
  → UPSERT prix_extraits (ON CONFLICT ticket_id, line_index)
  → HTTP 204
```

#### Groq wiring in the worker

When `PRT_OCR_ENGINE=groq` (default), `ocr.py` sets before each call:

- `RECEIPT_OCR_BACKEND=vlm`
- `RECEIPT_VLM_MODEL=groq-llama4-scout`
- `RECEIPT_VLM_MODE=json`
- `reset_default_backend()` after env change (singleton cache)

Production must provide `GROQ_API_KEY` (or legacy `groq_key`) on Cloud Run — not a `PRT_*` variable.

#### Schema mapping (receipt_ocr → SQL)

| `receipt_ocr` | SQL |
|---------------|-----|
| `ticket.chaine_supermarche` | `tickets.enseigne` |
| `ticket.date` (`yyyyMMdd HH:mm`) | `tickets.ticket_date` (`date`) |
| Σ `prix × unites` | `tickets.total_amount` |
| `produits[i].nom_produit` | `prix_extraits.raw_text` |
| `produits[i].prix_unitaire_ou_kg` | `prix_extraits.unit_price` |
| `produits[i].unites` | `prix_extraits.quantity` |
| — | `prix_extraits.ean = NULL`, `match_method = 'none'`, `needs_validation = TRUE` |

`ocr_confidence` defaults to `1.0` until the package exposes a real score (`# TODO` in `mapper.py` / `main.py`).

#### HTTP semantics (contract §2)

| Situation | HTTP | DB |
|-----------|------|-----|
| Success | 204 | `ocr_done` + `prix_extraits` |
| Bad Pub/Sub envelope | 400 | — |
| Image/OCR parse failure | 204 | `ocr_failed` (ACK, no DLQ) |
| Infra failure (DB, GCS 5xx) | 5xx | Pub/Sub retry |
| Already processed ticket | 204 | skip (idempotent) |

#### How to run / test

```powershell
cd workers/ocr
uv sync
$env:PRT_OIDC_DISABLE = "1"
uv run pytest -m "not integration"

# Docker image (monorepo root)
docker build -f workers/ocr/Dockerfile -t worker-ocr:local .
```

Integration tests (`pytest -m integration`): Postgres via testcontainers — requires Docker Desktop.

#### Still required for production

- Terraform: `run_worker_ocr` env vars + `GROQ_API_KEY` secret + image tag in `infra/envs/prod/cloud_run.tf`
- Alembic: `tickets` / `prix_extraits` tables (contract §6)
- Phase 8: EAN resolution (`matcher.py`, Vertex `RETRIEVAL_QUERY`, `product_aliases`)

#### References

- Worker contract: [`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md)
- Implementation prompt: [`workers/ocr/cursor_prompt_ocr_worker.md`](../../../workers/ocr/cursor_prompt_ocr_worker.md)
- Package reference: [`workers/ocr/dev_ocr_codebase_reference_for_llm.md`](../../../workers/ocr/dev_ocr_codebase_reference_for_llm.md)
- Groq provider in library: Entry 7–8 in this file

---
