# Cursor Prompt — Build `workers/ocr/` from `dev\_ocr/` per Contract

## Context

You are implementing the production Cloud Run worker `prt-prod-worker-ocr` inside `workers/ocr/`.  
The OCR extraction logic already exists in `dev\_ocr/src/receipt\_ocr/` (a standalone Python package).  
Your job is **not** to rewrite that package — it is to build the worker shell around it and wire it to
GCS, Pub/Sub, and Cloud SQL following the contract in `workers/ocr/ocr-worker-contract.md`.

Read the following files **before writing any code**:

* `workers/ocr/ocr-worker-contract.md` — authoritative production spec
* `workers/ocr/dev\_ocr\_codebase\_reference\_for\_llm.md` (or the equivalent codebase doc) — describes `receipt\_ocr` internals

\---

## Scope restriction — what you MUST NOT implement

> \*\*EAN matching / embedding / pgvector lookup is explicitly out of scope.\*\*

Concretely:

* Do **not** call Vertex AI embeddings.
* Do **not** query `products` table for cosine similarity.
* Do **not** run rapidfuzz on `product\_aliases`.
* In every `prix\_extraits` row, set `ean = NULL`, `match\_method = 'none'`, `match\_confidence = NULL`.
* `needs\_validation = TRUE` for every line (since EAN is always unresolved).
* Do **not** create `matcher.py` or `vertex.py` (they belong to a later phase).
* Do **not** INSERT into `product\_aliases` (that is a side-effect of EAN matching).
* Variables `PRT\_EAN\_\*`, `PRT\_VERTEX\_\*` can be declared in `config.py` as optional/unused — they exist in the contract for future phases.

\---

## Deliverables

Create the following directory tree **exactly**:

```
workers/ocr/
├── Dockerfile
├── cloudbuild.yaml
├── pyproject.toml
├── .dockerignore
├── .gcloudignore
├── pricetracker\_ocr/
│   ├── \_\_init\_\_.py
│   ├── main.py
│   ├── auth.py          ← copy verbatim from workers/off/pricetracker\_off/auth.py
│   ├── config.py
│   ├── logging.py       ← copy verbatim from workers/off/pricetracker\_off/logging.py
│   ├── gcs.py
│   ├── ocr.py           ← thin adapter calling receipt\_ocr.extract\_receipt
│   ├── mapper.py        ← maps receipt\_ocr dict → SQL-ready dicts
│   ├── pg.py
│   └── pubsub.py
└── tests/
    ├── fixtures/
    │   └── pubsub\_envelope.json
    ├── test\_pubsub.py
    ├── test\_mapper.py
    ├── test\_pg.py
    └── test\_push\_endpoint.py
```

Do **not** create `matcher.py`, `vertex.py`, or `parser/` — those are future-phase.

\---

## File-by-file specifications

### `auth.py` and `logging.py`

Copy byte-for-byte from `workers/off/pricetracker\_off/auth.py` and
`workers/off/pricetracker\_off/logging.py`. Do not modify them. Import them
in `main.py` exactly as the OFF worker does.

\---

### `config.py`

Use `pydantic-settings` (`BaseSettings`). All fields use the `PRT\_` prefix convention.

Required fields (non-optional):

```python
google\_cloud\_project: str          # GOOGLE\_CLOUD\_PROJECT
prt\_gcp\_region: str                # PRT\_GCP\_REGION
prt\_bronze\_bucket: str             # PRT\_BRONZE\_BUCKET
prt\_ocr\_engine: str = "groq"       # PRT\_OCR\_ENGINE  ("groq" | "paddleocr" | "tesseract")
prt\_ocr\_confidence\_threshold: float = 0.55
prt\_pg\_host: str
prt\_pg\_port: int = 5432
prt\_pg\_db: str
prt\_pg\_user: str
prt\_pg\_password: str               # from Secret Manager in prod
prt\_pg\_pool\_size: int = 4
prt\_oidc\_allowed\_service\_accounts: str
prt\_log\_level: str = "INFO"
```

Optional/future-phase (declare but do not use in logic):

```python
prt\_models\_bucket: str | None = None
prt\_ocr\_model\_uri: str | None = None
prt\_ean\_match\_cosine\_threshold: float = 0.78
prt\_ean\_match\_top\_k: int = 5
prt\_ean\_fuzzy\_min\_score: int = 82
prt\_vertex\_model: str = "text-embedding-004"
prt\_vertex\_output\_dim: int = 768
prt\_vertex\_task\_type: str = "RETRIEVAL\_QUERY"
prt\_oidc\_disable: bool = False     # PRT\_OIDC\_DISABLE — local bypass only
```

Expose a `get\_settings()` function with `@lru\_cache`.

\---

### `pubsub.py`

Implement `parse\_pubsub\_envelope(body: bytes) -> tuple\[str, str]`
returning `(gcs\_bucket, gcs\_object\_path)`.

* Decode the outer JSON: `{ "message": { "data": "<base64>", "attributes": {...} }, "subscription": "..." }`.
* Base64-decode `message.data` → parse inner JSON (`storage#object`).
* Return `(data\["bucket"], data\["name"])`.
* Raise `ValueError` for any structural issue (caller sends HTTP 400).
* `gcs\_object\_path` format is always `"tickets/raw/{user\_id}/{uuid}.jpg"`.
Extract `ticket\_id` (the UUID) from the path: split on `/`, take the last segment, strip extension.

Also implement `extract\_ticket\_id(gcs\_object\_path: str) -> str`:

* Parses `tickets/raw/{user\_id}/{uuid}.ext` → returns `uuid` string.
* Raises `ValueError` if path doesn't match expected pattern.

\---

### `gcs.py`

Implement `async def download\_image(bucket: str, object\_path: str) -> bytes`.

* Use `google-cloud-storage` with ADC (`google.auth.default()`).
* Size guard: if `blob.size > 10 \* 1024 \* 1024` (10 MB), raise `ImageTooLargeError(path, size)`.
* Define `ImageTooLargeError(Exception)` in this file.
* Do **not** write to disk inside this function — return raw bytes.

\---

### `ocr.py`

This is a thin adapter between the worker and the `receipt\_ocr` package.

```python
import tempfile, os
from pathlib import Path
from receipt\_ocr import extract\_receipt, reset\_default\_backend
from receipt\_ocr.exceptions import ReceiptOcrError

def run\_ocr(image\_bytes: bytes, engine: str = "groq") -> dict:
    """
    Write bytes to a temp file, call extract\_receipt, return the raw dict.
    Raises OcrProcessingError on any ReceiptOcrError.
    """
```

Engine mapping:

* `"groq"` → set env `RECEIPT\_OCR\_BACKEND=vlm`, `RECEIPT\_VLM\_MODEL=groq-llama4-scout`,
`RECEIPT\_VLM\_MODE=json` before calling; `GROQ\_API\_KEY` must already be in env.
* `"paddleocr"` → set `RECEIPT\_OCR\_BACKEND=paddle`.
* `"tesseract"` → set `RECEIPT\_OCR\_BACKEND=tesseract`.

Always call `reset\_default\_backend()` after changing env (the receipt\_ocr package caches the backend singleton).

Use `tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)` — write bytes, flush, close, then
pass path to `extract\_receipt`, then `os.unlink` in a `finally` block.

Define `OcrProcessingError(Exception)` in this file; wrap all `ReceiptOcrError` into it.

**Important:** Do not modify anything in `dev\_ocr/src/receipt\_ocr/`. Only import from it.

\---

### `mapper.py`

Maps the `receipt\_ocr` canonical dict to the SQL row shapes expected by the contract.

```python
from datetime import date
from typing import Any

def map\_ticket\_fields(ocr\_result: dict, ticket\_id: str, gcs\_path: str, engine: str,
                      duration\_ms: int, confidence: float) -> dict:
    """
    Returns a dict matching the tickets table columns to UPDATE:
      enseigne, ticket\_date, total\_amount, ocr\_confidence,
      ocr\_engine, ocr\_duration\_ms
    """

def map\_prix\_extraits\_rows(ocr\_result: dict, ticket\_id: str) -> list\[dict]:
    """
    Returns a list of dicts, one per produit, matching prix\_extraits columns:
      ticket\_id, line\_index, raw\_text, quantity, unit\_price, line\_total,
      ean (always None), match\_method (always 'none'),
      match\_confidence (always None), needs\_validation (always True),
      validated\_by\_user (always False)
    """
```

**Schema mapping** (receipt\_ocr canonical → SQL contract):

|`receipt\_ocr` field|SQL column|
|-|-|
|`ticket.chaine\_supermarche`|`tickets.enseigne`|
|`ticket.date` (string `"yyyyMMdd HH:mm"`)|`tickets.ticket\_date` (parse to `datetime.date`)|
|sum of all `produits\[].prix\_unitaire\_ou\_kg \* unites`|`tickets.total\_amount`|
|`produits\[i].nom\_produit`|`prix\_extraits.raw\_text`|
|`produits\[i].prix\_unitaire\_ou\_kg`|`prix\_extraits.unit\_price`|
|`produits\[i].unites`|`prix\_extraits.quantity`|
|`unit\_price \* quantity`|`prix\_extraits.line\_total`|
|loop index `i`|`prix\_extraits.line\_index`|

Date parsing: input is `"%Y%m%d %H:%M"` → output is a `datetime.date`. If empty string or unparseable, set `None`.

`total\_amount`: prefer `tickets.total\_amount` from OCR if the parser ever adds it; for now compute as sum of `line\_total` values across all lines.

`ocr\_confidence`: the `receipt\_ocr` package does not expose a confidence score at the top level. Default to `1.0` if none is available (the VLM path has no per-token confidence). Make this obvious with a `# TODO: derive real confidence` comment.

\---

### `pg.py`

Use `asyncpg`. Implement:

```python
async def create\_pool(settings) -> asyncpg.Pool

async def set\_ticket\_processing(pool, ticket\_id: str) -> bool:
    """
    UPDATE tickets SET status='ocr\_processing', updated\_at=now()
    WHERE id=$1 AND status IN ('pending','uploaded')
    Returns True if 1 row affected, False if 0 (already processed — idempotent).
    """

async def set\_ticket\_done(pool, ticket\_id: str, fields: dict) -> None:
    """
    UPDATE tickets SET status='ocr\_done', enseigne=$2, ticket\_date=$3,
      total\_amount=$4, ocr\_confidence=$5, ocr\_engine=$6, ocr\_duration\_ms=$7,
      updated\_at=now()
    WHERE id=$1
    """

async def set\_ticket\_failed(pool, ticket\_id: str, error\_message: str) -> None:
    """
    UPDATE tickets SET status='ocr\_failed', error\_message=$2, updated\_at=now()
    WHERE id=$1
    """

async def upsert\_prix\_extraits(pool, rows: list\[dict]) -> None:
    """
    INSERT INTO prix\_extraits (ticket\_id, line\_index, raw\_text, quantity,
      unit\_price, line\_total, ean, match\_method, match\_confidence,
      needs\_validation, validated\_by\_user)
    VALUES (...)
    ON CONFLICT (ticket\_id, line\_index)
    DO UPDATE SET
      raw\_text=EXCLUDED.raw\_text,
      quantity=EXCLUDED.quantity,
      unit\_price=EXCLUDED.unit\_price,
      line\_total=EXCLUDED.line\_total,
      ean=EXCLUDED.ean,
      match\_method=EXCLUDED.match\_method,
      match\_confidence=EXCLUDED.match\_confidence,
      needs\_validation=EXCLUDED.needs\_validation
    Use executemany for batch efficiency.
    """
```

Use `asyncpg.create\_pool(dsn=..., min\_size=1, max\_size=settings.prt\_pg\_pool\_size)`.
Build DSN from `prt\_pg\_host`, `prt\_pg\_port`, `prt\_pg\_db`, `prt\_pg\_user`, `prt\_pg\_password`.

\---

### `main.py`

FastAPI application. Mount only two endpoints:

#### `GET /healthz`

No auth. Returns `{"status": "ok"}` with HTTP 200.

#### `POST /push`

Auth: call `verify\_oidc(request)` from `auth.py`. On `401` → return 401 immediately.

Full request handler — implement exactly this pipeline:

```
1. Parse body as JSON → call pubsub.parse\_pubsub\_envelope(body)
   On ValueError → log warning, return HTTP 400

2. Extract ticket\_id = pubsub.extract\_ticket\_id(gcs\_object\_path)
   On ValueError → return HTTP 400

3. Log push\_received (ticket\_id, gcs\_path, subscription)

4. pg: await set\_ticket\_processing(pool, ticket\_id)
   If returns False → log "ticket already processed, skipping (idempotent)" → return HTTP 204

5. t\_start = time.monotonic()
   Try:
     a. image\_bytes = await gcs.download\_image(bucket, gcs\_object\_path)
     b. ocr\_result  = ocr.run\_ocr(image\_bytes, engine=settings.prt\_ocr\_engine)
     c. duration\_ms = int((time.monotonic() - t\_start) \* 1000)
     d. ticket\_fields = mapper.map\_ticket\_fields(ocr\_result, ticket\_id, gcs\_object\_path,
                          settings.prt\_ocr\_engine, duration\_ms, confidence=1.0)
     e. prix\_rows = mapper.map\_prix\_extraits\_rows(ocr\_result, ticket\_id)
     f. await pg.set\_ticket\_done(pool, ticket\_id, ticket\_fields)
     g. await pg.upsert\_prix\_extraits(pool, prix\_rows)
     h. log ocr\_done event (see §12 of contract for fields)
     i. return HTTP 204

   Except ImageTooLargeError, OcrProcessingError, ReceiptParseError, ValueError as fatal\_err:
     # Non-retryable: data / image problem
     await pg.set\_ticket\_failed(pool, ticket\_id, str(fatal\_err))
     log ocr\_failed (ticket\_id, error=str(fatal\_err), retryable=False)
     return HTTP 204   ← ACK so Pub/Sub does NOT retry

   Except Exception as transient\_err:
     # Retryable: DB down, GCS 5xx, etc.
     log ocr\_failed (ticket\_id, error=str(transient\_err), retryable=True)
     raise  # → FastAPI returns 500 → Pub/Sub retries
```

**App lifespan**: use FastAPI `lifespan` context manager to create the asyncpg pool on startup and
close it on shutdown. Store pool in `app.state.pool`.

Log all structured events using `structlog` (copy pattern from OFF worker). Every log event MUST
include `ticket\_id` as a bound variable. Mandatory named events: `push\_received`, `ocr\_start`,
`ocr\_done`, `ocr\_failed`, `pg\_upsert\_done`.

`ocr\_done` log must include (per contract §12):

```python
log.info("ocr\_done",
    ticket\_id=ticket\_id, user\_id=user\_id\_from\_path, gcs\_path=gcs\_object\_path,
    duration\_ms=duration\_ms, n\_lines=len(prix\_rows),
    n\_resolved\_vector=0, n\_resolved\_fuzzy=0,  # always 0 — EAN phase not implemented
    n\_needs\_validation=len(prix\_rows),
    ocr\_confidence=1.0,
    image\_bytes=len(image\_bytes),
    model\_version=settings.prt\_ocr\_engine)
```

\---

### `pyproject.toml`

```toml
\[project]
name = "pricetracker-ocr"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = \[
    "fastapi>=0.111",
    "uvicorn\[standard]>=0.29",
    "google-cloud-storage>=2.16",
    "asyncpg>=0.29",
    "pydantic-settings>=2.2",
    "structlog>=24.1",
    "groq>=0.13",
    "Pillow>=10.0",
    "json-repair>=0.30",
    "python-dotenv>=1.0",
    # receipt\_ocr is installed from dev\_ocr/src (see Dockerfile)
]
```

Note: `receipt\_ocr` package is **not** published to PyPI. In the Dockerfile, install it via:
`COPY dev\_ocr/src /app/receipt\_ocr\_src` then `pip install /app/receipt\_ocr\_src`.
Or via `pip install -e /app/receipt\_ocr\_src` if dev mode is acceptable.

\---

### `Dockerfile`

Multi-stage, python:3.11-slim. Do **not** embed OCR model weights (downloaded at runtime for
classical backends; Groq is cloud API so no local model needed).

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY workers/ocr/pyproject.toml .
RUN pip install --upgrade pip \&\& pip install build
COPY workers/ocr/ .
RUN pip install --no-cache-dir .

# Install receipt\_ocr package from dev\_ocr/src
COPY dev\_ocr/src /receipt\_ocr\_src
RUN pip install --no-cache-dir /receipt\_ocr\_src

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin
COPY workers/ocr/pricetracker\_ocr /app/pricetracker\_ocr

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD \["uvicorn", "pricetracker\_ocr.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Adapt the COPY paths to match the actual monorepo layout if needed. The key constraint is that
`receipt\_ocr` must be importable inside the container.

\---

### `cloudbuild.yaml`

Mirror `workers/off/cloudbuild.yaml`. Replace `worker-off` with `worker-ocr`. Image tag driven by
`$SHORT\_SHA`. Push to `europe-west1-docker.pkg.dev/price-tracker-prod-01/prt-prod-docker/worker-ocr:$SHORT\_SHA`.

\---

## Tests to write

### `tests/fixtures/pubsub\_envelope.json`

A real-shape Pub/Sub push payload (JSON\_API\_V1). The `data` field should be a valid base64-encoded
`storage#object` JSON where `name = "tickets/raw/user-abc-123/550e8400-e29b-41d4-a716-446655440000.jpg"`.

### `tests/test\_pubsub.py` — unit

* `parse\_pubsub\_envelope` happy path returns correct bucket + path.
* `parse\_pubsub\_envelope` raises `ValueError` on missing `message.data`.
* `extract\_ticket\_id` returns correct UUID from valid path.
* `extract\_ticket\_id` raises `ValueError` on malformed path.

### `tests/test\_mapper.py` — unit

* `map\_ticket\_fields` correctly maps `chaine\_supermarche` → `enseigne`.
* `map\_ticket\_fields` parses `"20240315 14:30"` → `date(2024, 3, 15)`.
* `map\_ticket\_fields` returns `None` for `ticket\_date` when OCR date is empty string.
* `map\_prix\_extraits\_rows` sets `ean=None`, `match\_method='none'`, `needs\_validation=True` on all rows.
* `map\_prix\_extraits\_rows` assigns correct `line\_index` (0-based).
* `map\_prix\_extraits\_rows` computes `line\_total = unit\_price \* quantity`.

### `tests/test\_pg.py` — integration (mark `@pytest.mark.integration`)

Use `testcontainers` with image `pgvector/pgvector:pg15`.

Before tests, run the DDL from contract §6 (tickets, prix\_extraits tables). You'll need a minimal
`users` table too (just `id uuid PRIMARY KEY`) to satisfy the FK.

* `set\_ticket\_processing` returns `True` when status is `'pending'`.
* `set\_ticket\_processing` returns `False` when called a second time (idempotent).
* `upsert\_prix\_extraits` inserts rows; calling again with same `(ticket\_id, line\_index)` does not duplicate.
* `set\_ticket\_failed` writes correct error\_message and status.

### `tests/test\_push\_endpoint.py` — contract

Use `httpx.AsyncClient` with FastAPI's `TestClient` or `AsyncClient(transport=ASGITransport(...))`.
Mock: `pg.create\_pool`, `gcs.download\_image`, `ocr.run\_ocr`, `pg.set\_ticket\_processing`,
`pg.set\_ticket\_done`, `pg.upsert\_prix\_extraits`.

* Happy path: valid Pub/Sub envelope + mocked OCR result → HTTP 204, `set\_ticket\_done` called once.
* Idempotent: `set\_ticket\_processing` returns `False` → HTTP 204, `run\_ocr` never called.
* Corrupt image: `run\_ocr` raises `OcrProcessingError` → HTTP 204, `set\_ticket\_failed` called.
* Bad envelope: malformed JSON body → HTTP 400.
* OIDC disabled (`PRT\_OIDC\_DISABLE=1`) for all tests — mock or disable auth.

\---

## Constraints \& reminders

1. **No BigQuery** anywhere in this worker.
2. **ADC only** — no service account key files, no `google.oauth2.service\_account.Credentials`.
3. `receipt\_ocr` package: import from it, never modify it.
4. `auth.py`, `logging.py`: copied from OFF worker, never modified.
5. Every log event must have `ticket\_id` as a bound structlog context variable (use
`structlog.contextvars.bind\_contextvars(ticket\_id=ticket\_id)` at the top of the `/push` handler).
6. HTTP contract (hard rules from §2 of contract):

   * Transient infra errors → 5xx (let Pub/Sub retry, max 5 times before DLQ).
   * Data/image errors → 204 (mark `ocr\_failed`, ACK to prevent DLQ pollution).
   * Bad Pub/Sub envelope → 400.
7. `ack\_deadline\_seconds = 600` — total budget. Keep OCR call timeout well under 540s
(FastAPI `timeout\_seconds=540` on Cloud Run).
8. Dockerfile must **not** `COPY` PaddleOCR model weights — models are downloaded at runtime to
`/tmp` (classical backends only; Groq path has no local model).
9. Add `# Phase 8 — EAN matching not yet implemented` comments in `main.py` and `mapper.py`
wherever EAN resolution would eventually happen, so the next developer knows exactly where to slot it in.

