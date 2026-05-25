## Version 0.1.3 (unreleased)

### Entry 7 — 2026-05-25 (UTC+2)

**Scope:** Add a **Groq cloud vision** provider as a swappable VLM implementation, returning structured receipt JSON via the existing VLM pipeline (no new top-level OCR backend).

#### Motivation

Local Moondream 0.5B is fast to iterate offline but struggles on difficult phone photos (empty products, chatty headers). Groq hosts multimodal models with vision + JSON mode at low latency, which fits a **cloud alternative** that still plugs into the same `VlmBackend` / `ReceiptParser` architecture so backends remain easy to compare (`moondream-0.5b` vs `groq-llama4-scout` via one env var).

Design constraints agreed for this work:

| Constraint | Implementation |
|------------|----------------|
| Use Groq vision, not OpenAI GPT-4o | API model `meta-llama/llama-4-scout-17b-16e-instruct` (configurable) |
| Keep `RECEIPT_OCR_BACKEND=vlm` | New `GroqProvider` only; no `BackendName.GROQ` |
| Output always matches README JSON schema | Force `RECEIPT_VLM_MODE=json`; normalize via `try_parse_vlm_json` |
| Swappable VLM providers | Registry id `groq-llama4-scout` in `build_vlm_provider()` |
| Non-JSON VLM modes must error | `GroqProvider.__init__` raises `OcrBackendError` if mode ≠ `json` |
| Groq tests must hit the real API | `@pytest.mark.groq` integration tests; no mocked Groq HTTP |

#### What was implemented

| Component | File | Role |
|-----------|------|------|
| Groq provider | `backends/vlm/groq_provider.py` | `VlmProvider`: base64 image upload, chat completions, `response_format=json_object` |
| Registry | `backends/vlm/registry.py` | `groq-llama4-scout` → `GroqProvider` |
| Constants | `constants.py` | `VlmModelName.GROQ_LLAMA4_SCOUT`, `ENV_GROQ_*`, `DEFAULT_GROQ_MODEL`, base64 size cap |
| Env loading | `env.py` | `load_project_env()` reads `.env` from repo root (`python-dotenv`) |
| Entry point | `extract_receipt.py` | Calls `load_project_env()` on import |
| Optional deps | `requirements-groq.txt` | `groq`, `python-dotenv`, `Pillow`, `json-repair` |
| Example env | `.env.example` | Documents `GROQ_API_KEY` / `groq_key` |
| Append script | `scripts/add_entry_to_documentation.py` | Append changelog chunks without editing the full doc |
| Smoke script | `scripts/test_groq_receipt.py` | One-image extraction + timing |
| Guardrail tests | `tests/test_groq_provider.py` | Rejects `transcribe` / `multipass` without calling API |
| Live API tests | `tests/test_groq_integration.py` | Real Groq + real images; asserts README schema |
| Pytest config | `conftest.py`, `pyproject.toml` | `groq` marker; skip if API key missing |

**Unchanged (reused as-is):** `VlmBackend`, `run_vlm_extraction()`, `prompts.py` (`RECEIPT_EXTRACTION_*`), `vlm_validate.py`, `vlm_parse.py`, `ReceiptParser.parse_text()`.

#### End-to-end flow (Groq)

```text
extract_receipt(image)
  → VlmBackend (RECEIPT_OCR_BACKEND=vlm)
  → build_vlm_provider("groq-llama4-scout")
  → run_vlm_extraction()  [RECEIPT_VLM_MODE=json, retries, validation]
  → GroqProvider.analyze_with_options()
       → prepare_vlm_image()  (crop / resize / JPEG)
       → Groq chat.completions (vision + JSON mode)
  → ReceiptParser.parse_text(JSON string)
  → try_parse_vlm_json() / normalize_vlm_ticket()
  → dict matching README schema
```

#### Groq API details

- **Endpoint:** Groq OpenAI-compatible `chat.completions.create`
- **Default model:** `meta-llama/llama-4-scout-17b-16e-instruct` (override with `RECEIPT_GROQ_MODEL`)
- **Image input:** Local file → JPEG temp from `prepare_vlm_image` → `data:image/jpeg;base64,...`
- **JSON mode:** `response_format={"type": "json_object"}` on every request
- **Size limit:** Groq rejects base64 payloads > 4 MB; provider checks raw file size (`GROQ_BASE64_MAX_BYTES` ≈ 3.5 MB) and suggests lowering `RECEIPT_VLM_MAX_IMAGE_SIDE` if exceeded

#### Environment variables (Groq-specific)

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_API_KEY` | — | Primary API key (Groq convention) |
| `groq_key` | — | Legacy name (read from `.env` today) |
| `RECEIPT_GROQ_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq API model id |
| `RECEIPT_VLM_MODEL` | — | Must be `groq-llama4-scout` to select this provider |
| `RECEIPT_VLM_MODE` | — | **Must be `json`** (enforced at provider init) |
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1536` | Shared with Moondream image prep |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | Shared retry / strict-prompt logic |
| `RECEIPT_VLM_TEMPERATURE` | `0.1` | Passed to Groq |
| `RECEIPT_VLM_MAX_TOKENS` | `1024` | Maps to `max_completion_tokens` |

Shared VLM vars (`RECEIPT_VLM_CROP`, `RECEIPT_VLM_JPEG_QUALITY`, etc.) behave the same as for Moondream.

#### How to run

```powershell
pip install -r requirements-groq.txt
# .env at repo root: GROQ_API_KEY=...  (or groq_key=...)

$env:PYTHONPATH = "src"
$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODEL = "groq-llama4-scout"
$env:RECEIPT_VLM_MODE = "json"

python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/your_ticket.jpg
```

Programmatic provider swap (same public API):

```python
from receipt_ocr import extract_receipt
from receipt_ocr.backends.vlm import build_vlm_provider
from receipt_ocr.backends.vlm_backend import VlmBackend

backend = VlmBackend(provider=build_vlm_provider("groq-llama4-scout"))
data = extract_receipt("ticket.jpg", backend=backend)
```

#### Testing

| Command | What it runs |
|---------|----------------|
| `pytest tests/test_groq_provider.py --no-integration` | Mode guardrails only (no HTTP) |
| `pytest -m groq` | Live Groq API on up to 3 images in `images_tickets_caisse/` |
| `pytest --no-integration` | Skips `@pytest.mark.groq` integration tests |

Groq integration tests are skipped when:

- `--no-integration` is passed, or
- No receipt images under `data/raw/`, or
- Neither `GROQ_API_KEY` nor `groq_key` is set.

**Verified (2026-05-25):** `pytest -m groq` — 1 passed (~5 s) on a local receipt image with `.env` key loaded.

#### Security / repo hygiene

- `.env` added to `.gitignore` (was not ignored before)
- `.env.example` committed with placeholders only
- **Rotate the Groq key** if `.env` was ever committed or shared

#### References

- User-facing setup: [`README.md`](README.md) — section “Groq vision (cloud, JSON receipts)”
- Groq vision docs: https://console.groq.com/docs/vision
- Moondream VLM baseline: Entry 6 in this file (local 0.5B modes)

---
