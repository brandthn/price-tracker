# Documentation — receipt_ocr

Changelog and implementation notes for the `dev_ocr` module. Each version groups one or more dated entries.

To append a new chunk without editing this file by hand:

```bash
python scripts/add_entry_to_documentation.py --file documentation/entries/your-entry.md
```

---

## Version 0.1.0

### Entry 1 — 2026-05-19 20:00 (UTC+2)

**Scope:** Initial implementation of the `receipt_ocr` package as specified in [`project_guidelines.md`](project_guidelines.md).

#### Summary

A standalone, importable Python package was added to extract structured data from photos of French supermarket receipts (*tickets de caisse*). The design follows the **Strategy pattern**: OCR backends are interchangeable; parsing logic is backend-agnostic.

#### Public API

```python
from receipt_ocr import extract_receipt

data = extract_receipt("path/to/ticket.jpg")
```

Output schema:

```json
{
  "ticket": {
    "date": "yyyyMMdd HH:mm",
    "chaine_supermarche": "nom",
    "adresse": "adresse complète",
    "produits": [
      {
        "nom_produit": "nom",
        "prix_unitaire_ou_kg": 0.00,
        "unites": 1
      }
    ]
  }
}
```

#### Source layout (`src/receipt_ocr/`)

| File | Role |
|------|------|
| `__init__.py` | Public exports: `extract_receipt`, `ReceiptParser`, exceptions |
| `extract_receipt.py` | Entry point + `build_backend()` factory |
| `parser.py` | `ReceiptParser`: raw OCR text → structured dict |
| `constants.py` | Field enums (`TicketField`, `ProductField`, `BackendName`), `RECEIPT_OCR_BACKEND` |
| `exceptions.py` | `ReceiptOcrError`, `OcrBackendError`, `ReceiptParseError` |
| `backends/base.py` | Abstract `OcrBackend` with `extract_text()` |
| `backends/paddle_backend.py` | Working `PaddleOcrBackend` (lazy import) |
| `backends/tesseract_backend.py` | Stub → `NotImplementedError` |
| `backends/easyocr_backend.py` | Stub → `NotImplementedError` |
| `backends/vlm_backend.py` | Stub → `NotImplementedError` |

#### Backend selection

- **Explicit:** `extract_receipt(path, backend=MyBackend())`
- **Environment:** `RECEIPT_OCR_BACKEND` = `paddle` \| `tesseract` \| `easyocr` \| `vlm` (default: `paddle`)
- Third-party imports are deferred to backend instantiation so `import receipt_ocr` works without any OCR library installed.

#### Parser behaviour (`ReceiptParser`)

- **Header:** chain name and address inferred from the first lines (no hardcoded supermarket brands).
- **Date:** French formats (`DD/MM/YYYY HH:MM`, etc.) converted to `yyyyMMdd HH:mm`.
- **Products:** lines ending with a price; quantity lines (`3 x 1,29`); per-kg lines (`0,452 kg x 5,98 €/kg`).
- **Footer:** totals, TVA, loyalty, payment lines ignored via keyword heuristics.
- Header line indices are tracked and skipped during product extraction (avoids fixed line-count bugs).

#### Tests (`tests/`)

| File | Coverage |
|------|----------|
| `test_parser.py` | Happy path, quantity/weight lines, missing date, empty OCR, footer filtering, error propagation |
| `test_extract_receipt.py` | Public API, backend swap, env variable, stub backends, `FileNotFoundError` |
| `test_paddle_backend.py` | Mocked PaddleOCR: flatten output, path validation, `OcrBackendError` wrapping |
| `test_integration_real_images.py` | Real images under `data/raw/` (`@pytest.mark.integration`) |
| `fixtures/sample_texts.py` | In-memory OCR text fixtures (no images required) |

**Run results (unit tests, no PaddleOCR installed):** `26 passed`, `24 skipped` (integration tests skip when PaddleOCR is missing or `--no-integration` is passed).

#### Root configuration

| File | Role |
|------|------|
| `conftest.py` | `integration` marker, `--no-integration` flag, auto-skip when `data/raw/` has no images, `src/` on `sys.path` |
| `pyproject.toml` | Package metadata + pytest config |
| `requirements.txt` | Runtime and dev dependencies |
| `README.md` | Install, usage, dataset download, adding a new backend |

#### Scripts

- **`scripts/download_datasets.py`** — Parses `data/raw/ocr_testing/datasets_to_use_for_testing.txt`, downloads HuggingFace and Kaggle datasets into `data/raw/` (idempotent, skips existing targets).

  Detected datasets from the list file:
  - HuggingFace: `shirastromer/supermarket-receipts`
  - Kaggle: `sushmithanarayan/expenses-receipt-ocr`

#### Data already present (not created in this version)

- `data/raw/images_tickets_caisse/` — local receipt photos for manual / integration testing.
- `data/raw/ocr_testing/datasets_to_use_for_testing.txt` — dataset references for the download script.

#### Design constraints respected

- Source under `src/`, tests under `tests/`, images under `data/raw/`.
- No hardcoded chain names.
- Unit tests: no network, no real images, no OCR library required.
- Integration tests: skipped gracefully when data or PaddleOCR is absent.

#### Not done in this version

- Full implementations of `TesseractBackend`, `EasyOcrBackend`, `VlmBackend`.
- End-to-end validation on all real receipt images (integration tests exist but depend on PaddleOCR + optional dataset download).
- CI pipeline configuration.

#### References

- Specification: [`project_guidelines.md`](project_guidelines.md)
- User guide: [`README.md`](README.md)

### Entry 2 — 2026-05-19 21:00 (UTC+2)

**Scope:** First pass at performance fixes (superseded in detail by Entry 3).

#### Changes (initial)

| Area | Change |
|------|--------|
| `paddle_backend.py` | Image resize, CPU thread cap, PaddleOCR 3.x `predict()` API |
| `extract_receipt.py` | Singleton cache for default backend |
| `constants.py` | `RECEIPT_OCR_MAX_IMAGE_SIDE`, `RECEIPT_OCR_CPU_THREADS` |
| Integration tests | Scoped to `images_tickets_caisse/` + `--integration-max-images` |
| `scripts/smoke_test_ocr.py` | One-image CLI smoke test |

---
## Version 0.1.1

### Entry 3 — 2026-05-23 15:00 (UTC+2)

**Scope:** Diagnose and fix PC freezes during PaddleOCR testing; complete the end-to-end pipeline on a real receipt (`4PQOWWaPoa.jpg`); harden parser for real-world OCR layouts.

#### Problem observed

Running `PaddleOcrBackend` or `pytest -m integration` caused the machine to appear frozen (100 % CPU, minutes without response). This was **not** an infinite loop in our code, but a combination of:

| Factor | Why it hurts on a laptop |
|--------|---------------------------|
| **PaddleOCR / PaddlePaddle** | Large models, high RAM use, aggressive multi-threading (oneDNN / OpenMP) |
| **PaddleOCR 3.x API change** | Old code used `show_log`, `use_angle_cls`, `.ocr(cls=True)` — init failed or behaved incorrectly |
| **`paddle_static` on Windows** | Default mobile det weights require `paddle_static`; triggers oneDNN `NotImplementedError` on some Windows builds |
| **Full-resolution photos** | e.g. `4PQOWWaPoa.jpg` (~2.3 MB) sent to OCR with no downscaling |
| **Reloading models every call** | `extract_receipt(path)` without `backend=` created a new `PaddleOcrBackend()` each time |
| **Integration tests on ~395 images** | `data/raw/` + Kaggle cache discovered hundreds of files; one OCR per image = hours at 100 % CPU |
| **Cold start** | First run downloads/loads `PP-OCRv5_server_det` + `latin_PP-OCRv5_mobile_rec` (~30–90 s) |

#### Considerations that drove the design

1. **Stability over raw speed on Windows** — use `engine="paddle_dynamic"` by default (known to work); keep `use_mobile_models=False` unless on Linux/server where `paddle_static` is reliable.
2. **Bound resource usage** — cap CPU threads (`RECEIPT_OCR_CPU_THREADS=2`), resize before OCR (`RECEIPT_OCR_MAX_IMAGE_SIDE=1280`), disable MKL-DNN (`enable_mkldnn=False`, `FLAGS_use_mkldnn=0`).
3. **Load models once** — cache the default backend in `build_backend()`; document explicit reuse for batch scripts.
4. **Safe local testing** — smoke script for one image; integration tests limited to `images_tickets_caisse/` with `--integration-max-images` (default 3).
5. **Real receipt layouts** — OCR often splits product name, unit price, line total, and quantity (`2 x`) across lines; parser must handle that, plus date/time on separate lines (`15/10/24` + `12:40`).
6. **Skip PaddleX network check** — `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` set in code to avoid slow host connectivity checks.

#### What was implemented

| Area | Implementation |
|------|----------------|
| **`paddle_backend.py`** | PaddleOCR 3.x: `predict()` → `rec_texts` / `rec_scores`; auto engine (`paddle_dynamic` default); image resize via Pillow; `text_det_limit_side_len`; thread limits; optional `use_mobile_models=True` → `paddle_static` with fallback |
| **`extract_receipt.py`** | `_cached_backend` singleton; `reset_default_backend()` for tests |
| **`parser.py`** | Multi-line products (name → unit price → total → `N x`); split date/time; section headers (`> PATES`); multi-line weight (`0,972 kg` + `2,79 €/kg`); fixture `tests/fixtures/super_u_ocr_text.py` |
| **`constants.py`** | `ENV_MAX_IMAGE_SIDE`, `ENV_CPU_THREADS`, `DEFAULT_MAX_IMAGE_SIDE=1280`, `PADDLE_MOBILE_DET_MODEL` |
| **`conftest.py`** | `--integration-max-images`, `--integration-all-data` |
| **`test_integration_real_images.py`** | `pytest_generate_tests` + session-scoped `paddle_backend` fixture |
| **`scripts/smoke_test_ocr.py`** | Single-image test with init/OCR timings; `--raw-only` flag |
| **`requirements.txt`** | Explicit `Pillow` |
| **Tests** | `33 passed` unit tests (`pytest --no-integration`); Super U multiline parser test |

#### Validated on `4PQOWWaPoa.jpg` (Super U)

Smoke test (`python scripts/smoke_test_ocr.py …`) on Windows / Python 3.11:

| Phase | Approx. duration |
|-------|------------------|
| Model init (first run) | ~35 s |
| OCR + parse (per large image, CPU) | ~100–120 s |

Example structured output (after parser fixes):

```json
{
  "ticket": {
    "date": "20241015 12:40",
    "chaine_supermarche": "SUPER(U",
    "adresse": "14 RUE PAUL, 75011",
    "produits": [
      { "nom_produit": "TORSADES COMPLETES U BIO 500G", "prix_unitaire_ou_kg": 1.1, "unites": 2 },
      { "nom_produit": "BOISSON SOJA NATURE U BIO 1L", "prix_unitaire_ou_kg": 0.88, "unites": 4 }
    ]
  }
}
```

(Full run extracts five products including raisin, chocolate, fish — see unit test `test_parse_super_u_multiline_layout`.)

#### How to test without freezing the PC

```powershell
$env:PYTHONPATH = "src"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:RECEIPT_OCR_CPU_THREADS = "2"

# One image (recommended)
python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg

# Raw OCR text only
python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg --raw-only

# Fast unit tests (no OCR, no GPU)
pytest --no-integration

# Integration: 3 images from images_tickets_caisse/ only
pytest -m integration
```

#### Pitfalls to avoid

- Do **not** call `extract_receipt()` in a tight loop without passing the same `backend=` instance.
- Do **not** run `pytest -m integration --integration-all-data` on a laptop unless you accept hours of CPU load.
- Do **not** enable `use_mobile_models=True` on Windows without expecting possible `paddle_static` / oneDNN errors.
- First OCR after install still downloads models to `~/.paddlex/` — plan for one slow cold start.

#### References

- User guide: [`README.md`](README.md)
- Specification: [`project_guidelines.md`](project_guidelines.md)

### Entry 4 — 2026-05-23 16:30 (UTC+2)

**Scope:** Add `PpOcrV4MobileBackend` (`RECEIPT_OCR_BACKEND=ppocrv4`) for faster inference.

#### Implementation

| Item | Detail |
|------|--------|
| New file | `src/receipt_ocr/backends/ppocr_v4_backend.py` |
| Registry | `BackendName.PPOCRV4` → `build_backend("ppocrv4")` |
| Defaults | `PP-OCRv4_mobile_det`, max side **640 px**, `paddle_static` first |
| Fallback | `paddle_dynamic` + server models if static init fails |
| Smoke script | `--backend ppocrv4` (now default in `smoke_test_ocr.py`) |

#### Benchmark on `4PQOWWaPoa.jpg` (Windows, CPU)

| Backend | Init | OCR+parse | Profile |
|---------|------|-----------|---------|
| `paddle` (v0.1 defaults) | ~35 s | ~104 s | `paddle_dynamic` + server det |
| `ppocrv4` | ~29 s | **~54 s** | `ppocrv4-static-mobile` |

Structured output: date + chain + 2 products (smaller image → fewer lines detected than full-res run; parser still valid).

#### Note on ONNX

`engine="onnxruntime"` is **not** accepted by PaddleOCR 3.5's pipeline constructor (only `paddle`, `paddle_static`, `paddle_dynamic`, `transformers`). True mobile ONNX deployment remains a future dedicated backend.

---

### Entry 5 — 2026-05-23 (UTC+2)

**Scope:** First VLM backend with pluggable providers; Moondream 0.5B as default.

#### Architecture

| Layer | Role |
|-------|------|
| `VlmBackend` | Implements `OcrBackend`; delegates to a `VlmProvider` |
| `VlmProvider` | ABC in `backends/vlm/base.py` |
| `build_vlm_provider()` | Registry — swap models via `RECEIPT_VLM_MODEL` |
| `MoondreamProvider` | Local `.mf` weights (cloud fallback disabled in dev) |
| `vlm_parse.py` | JSON-first parsing in `ReceiptParser.parse_text` |

#### Env vars

- `RECEIPT_OCR_BACKEND=vlm`
- `RECEIPT_VLM_MODEL=moondream-0.5b` (default)
- `RECEIPT_VLM_MODEL_PATH`, `RECEIPT_VLM_MAX_IMAGE_SIDE`
- Moondream Cloud API fallback **disabled** during dev (`_ENABLE_MOONDREAM_CLOUD = False` in `moondream_provider.py`)

#### Adding another VLM

1. New file `backends/vlm/<name>_provider.py` implementing `VlmProvider`
2. Register id in `VlmModelName` + `build_vlm_provider()`
3. Mocked unit test — no changes to `extract_receipt` or public API

#### Scripts & data

- **`scripts/download_moondream_weights.py`** — downloads `moondream-0_5b-int8.mf` into `data/models/` (gitignored)
- **`scripts/run_vlm_test.py`** — single-image VLM smoke test
- Weights path: `RECEIPT_VLM_MODEL_PATH` or auto-detect under `data/models/`

---

## Version 0.1.2

### Entry 6 — 2026-05-23 (UTC+2)

**Scope:** Improve local Moondream 0.5B extraction quality using VLM-only strategies (no 2B model, no OCR hybrid).

#### Problem observed (before this entry)

First VLM runs on real phone photos (`IMG_20260206_142131.jpg`) produced unusable JSON:

- Empty `produits` list
- Chatty `chaine_supermarche` values (e.g. `"Note: The image shows…"`)
- Model treating the task as conversational VQA instead of structured extraction

Root causes identified:

| Factor | Impact |
|--------|--------|
| **0.5B model capacity** | Too weak for one-shot full JSON on long, angled receipt photos |
| **Single JSON prompt** | Encourages explanatory text despite instructions |
| **1024 px resize + JPEG q=85** | Small thermal-print text lost |
| **Full photo with background** | Ticket occupies a fraction of the frame; model reads table/hands/floor |
| **No output validation** | Bad JSON accepted as-is |

#### Design decisions (explicit exclusions)

- **Local Moondream 0.5B only** — no 2B weights, no cloud API during dev (`_ENABLE_MOONDREAM_CLOUD = False`)
- **No OCR hybrid** — Paddle / ppocrv4 are not combined with VLM in the same pipeline
- **Reuse existing parser** — transcribe mode feeds line text into `ReceiptParser` heuristics

#### What was implemented

| Component | File | Role |
|-----------|------|------|
| Image prep | `vlm_image_prep.py` | Auto/center/off crop; resize at JPEG q=95 (default side **1536**) |
| Transcription cleanup | `vlm_text_cleanup.py` | Strip chatty lines, markdown fences |
| Output validation | `vlm_validate.py` | Reject empty/chatty/invalid chain names; drive retries |
| JSON parsing | `vlm_parse.py` | Fence stripping, embedded JSON extraction, `json-repair`, partial ticket merge |
| Extraction orchestrator | `backends/vlm/extraction.py` | Mode selection, retries, strict prompt fallback |
| Multi-pass mode | `backends/vlm/multipass.py` | 3 focused queries (header / date / products) merged into one ticket |
| Prompts | `backends/vlm/prompts.py` | Transcribe, strict transcribe, JSON, strict JSON, multipass prompts |
| Provider | `backends/vlm/moondream_provider.py` | `prepare_vlm_image`, `analyze_with_options`, `analyze_queries`, Moondream `settings` |
| Backend | `backends/vlm_backend.py` | Delegates to `run_vlm_extraction()` |
| Benchmark | `scripts/benchmark_vlm.py` | Compare `transcribe` / `json` / `multipass` on reference images |

#### Extraction modes (`RECEIPT_VLM_MODE`)

| Mode | Default | Flow |
|------|---------|------|
| **`transcribe`** | yes | VLM returns line-oriented text → `ReceiptParser` heuristics |
| `json` | | One-shot JSON → `vlm_parse` validation |
| `multipass` | | 3 small JSON queries; merge via `merge_partial_tickets()` |

Retry policy (`RECEIPT_VLM_MAX_RETRIES`, default **2**):

1. Normal prompt + default crop (`auto`)
2. Strict prompt + center crop
3. (if retries allow) repeat pattern

Failed validation raises `ReceiptParseError` with a snippet of the last output (fail loud, not silent garbage).

#### Environment variables (VLM)

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECEIPT_VLM_MODE` | `transcribe` | `transcribe` \| `json` \| `multipass` |
| `RECEIPT_VLM_MODEL` | `moondream-0.5b` | Provider registry id |
| `RECEIPT_VLM_MODEL_PATH` | `data/models/moondream-0_5b-int8.mf` | Local `.mf` weights |
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1536` | Resize longest side (`0` = off) |
| `RECEIPT_VLM_CROP` | `auto` | `auto` \| `center` \| `off` |
| `RECEIPT_VLM_CROP_MARGIN` | `0.05` | Padding around auto-detected receipt box |
| `RECEIPT_VLM_JPEG_QUALITY` | `95` | Temp image quality before inference |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | Retries after validation failure |
| `RECEIPT_VLM_TEMPERATURE` | `0.1` | Moondream generation temperature |
| `RECEIPT_VLM_MAX_TOKENS` | `1024` | Max tokens per query |

#### How to test

```powershell
pip install -r requirements-vlm.txt
python scripts/download_moondream_weights.py

$env:PYTHONPATH = "src"
$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODE = "transcribe"
$env:RECEIPT_VLM_CROP = "auto"
$env:RECEIPT_VLM_MAX_IMAGE_SIDE = "1536"

python scripts/run_vlm_test.py data/raw/images_tickets_caisse/IMG_20260206_142131.jpg
python scripts/benchmark_vlm.py
pytest --no-integration   # 70 passed, no Moondream required
```

Benchmark outputs saved under `data/benchmarks/vlm/` (gitignored).

#### Observed results on real images (Windows, CPU, local 0.5B)

| Image | Mode | Outcome |
|-------|------|---------|
| `IMG_20260206_142131.jpg` | `json` (v0.1.1) | Hallucinated chain, 0 products |
| `IMG_20260206_142131.jpg` | `transcribe` (v0.1.2) | 3 retries → `"[Text is illegible]"` → `ReceiptParseError` |
| `4PQOWWaPoa.jpg` | — | Not yet benchmarked post-v0.1.2; use `benchmark_vlm.py` |

The v0.1.2 pipeline **fails explicitly** instead of returning fabricated JSON — intended behaviour until quality improves.

#### Tests added

| File | Coverage |
|------|----------|
| `test_vlm_image_prep.py` | Crop + resize |
| `test_vlm_text_cleanup.py` | Chatty line removal |
| `test_vlm_validate.py` | Validation rules |
| `test_vlm_extraction.py` | Retry orchestration |
| `test_vlm_multipass.py` | Partial merge |
| Updated `test_vlm_backend.py`, `test_vlm_parse.py`, `test_extract_receipt.py` | Mode wiring |

**Run results:** `70 passed`, `3 skipped` (`pytest --no-integration`).

---

#### Next steps for Moondream 0.5B (considerations)

These are ordered by expected impact while staying on **local 0.5B only** and **VLM-only** (no Paddle hybrid, no 2B).

##### 1. Tune image input per photo type (high priority, low effort)

Phone photos vary widely. Before changing model code, sweep env vars on 5–10 reference tickets:

```powershell
# Full resolution (may help small text; slower, more RAM)
$env:RECEIPT_VLM_MAX_IMAGE_SIDE = "0"

# If auto-crop cuts the ticket, try:
$env:RECEIPT_VLM_CROP = "center"   # or "off"

python scripts/benchmark_vlm.py
```

Document winning defaults per image category (flat scan vs angled phone photo).

##### 2. Improve receipt cropping (medium priority)

Current auto-crop is Pillow-only contrast heuristics — fast but fragile on busy backgrounds.

Possible improvements (still no OCR):

- OpenCV contour + perspective warp (optional dependency)
- Detect bright rectangular region (thermal paper on dark table)
- Manual crop UI / CLI `--crop-box x,y,w,h` for dev dataset labelling
- Upscale cropped region (`RECEIPT_VLM_MIN_IMAGE_SIDE`) when ticket is small in frame

##### 3. Prompt & task decomposition (medium priority)

0.5B handles **narrow tasks** better than full receipts:

- Default to **`transcribe`**; use **`multipass`** when transcription is too short
- Add a **two-step transcribe**: (a) “list header lines only”, (b) “list product lines only”, then concatenate for `ReceiptParser`
- Few-shot prompt with a tiny fake ticket example (keep under token budget)
- French-only, shorter strict prompts for retry (already started — refine wording from benchmark logs)

##### 4. Validation & fallback between VLM modes (medium priority)

Automatic mode escalation within VLM-only:

```text
transcribe → (fail validation) → multipass → (fail) → json strict → ReceiptParseError
```

Log which stage succeeded for benchmark analysis. Implement in `extraction.py` without touching public API.

##### 5. Post-process transcription before parser (lower priority)

When transcribe returns partial text:

- Fix common 0.5B OCR-like errors (`|` → `I`, `0` vs `O` in prices)
- Split merged lines if price pattern `\d+[.,]\d{2}` appears mid-line
- Pass confidence hints: lines with `[illisible]` skipped, not parsed as products

##### 6. Benchmark dataset & metrics (high priority for project)

Build a small labelled set (10–20 local tickets) with expected product counts and chain names.

Track per mode:

- Product count vs ground truth
- Date/chain match rate
- Inference time (init + per image)
- Failure rate (`ReceiptParseError` vs success)

Use `scripts/benchmark_vlm.py` output in `data/benchmarks/vlm/` as regression history.

##### 7. Performance on CPU (lower priority unless mobile target)

0.5B local inference ~15–60 s/image on laptop CPU:

- Cache encoded image within a batch script (already done for `multipass` via `analyze_queries`)
- Keep model loaded (`build_backend()` cache already applies to `VlmBackend`)
- Consider `RECEIPT_VLM_MAX_IMAGE_SIDE=1280` for speed once quality baseline exists

##### 8. Explicit non-goals (for now)

| Approach | Why deferred |
|----------|--------------|
| Moondream 2B | User constraint — quality vs speed trade-off reserved for later experiment |
| Paddle + VLM hybrid | User constraint — keep backends independently evaluable |
| Cloud API | Disabled during dev — would mix local/cloud results |
| Fine-tuning 0.5B on receipts | School project scope — only if labelled dataset grows |

##### 9. Success criteria before moving on

- [ ] `IMG_20260206_142131.jpg` returns ≥ 1 product in **any** VLM mode, or documented as “unsupported angle/quality” with reason
- [ ] `4PQOWWaPoa.jpg` and 2 other tickets extract ≥ 50 % of products vs manual count
- [ ] `benchmark_vlm.py` run recorded in this doc with date and env snapshot
- [ ] Default env vars updated in README from benchmark winners

#### References

- VLM install & env: [`README.md`](README.md) — section “VLM backend (Moondream 0.5B)”
- Weights download: `scripts/download_moondream_weights.py`
- Specification: [`project_guidelines.md`](project_guidelines.md)

---

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

## Version 0.1.4 (unreleased)

### Entry 8 — 2026-05-25 (UTC+2)

**Scope:** Harden VLM JSON post-processing and Groq smoke-test reliability after duplicate / malformed outputs on real receipts.

#### Problem observed

Running `scripts/test_groq_receipt.py` on `4PQOWWaPoa.jpg` sometimes produced:

- The same product repeated several times (e.g. `RAISIN BLANC ITALIA` ×3–4)
- Concatenated or partial JSON blobs from the model (two `{ "ticket": ... }` blocks, truncated arrays)
- Dates in French form (`15/10/24`) instead of `yyyyMMdd HH:mm`
- Fractional `unites` (e.g. `0.972` for weight sold by kg), which broke strict integer validation

The README schema was not violated in structure, but `produits` could contain duplicates and parsing could fail validation retries.

#### What was implemented

| Area | File | Change |
|------|------|--------|
| Multi-JSON parsing | `vlm_parse.py` | `_collect_json_candidates`, `_loads_json` scores payloads and keeps the richest valid `ticket` |
| Product cleanup | `vlm_parse.py` | `_dedupe_vlm_products`, `_normalize_product_name`, `_round_price`; skip non-dict product rows |
| Date coercion | `vlm_parse.py` | `_coerce_vlm_date` for `DD/MM/YY`, `DD/MM/YYYY`, with/without time |
| Units coercion | `vlm_parse.py` | Fractional floats rounded to `max(1, round(value))` |
| Groq token budget | `constants.py`, `groq_provider.py` | `DEFAULT_GROQ_MAX_TOKENS = 4096` to reduce truncated JSON |
| Prompts | `backends/vlm/prompts.py` | No duplicate lines, single JSON object, integer `unites` |
| Smoke script | `scripts/test_groq_receipt.py` | `load_project_env()`, paths resolved from repo root, `chdir(ROOT)` |
| Tests | `tests/test_vlm_parse.py` | Dedup, multi-blob JSON, date/units coercion |

#### Cleaning pipeline (after Groq / any VLM JSON mode)

```text
raw model text
  → _collect_json_candidates (fences, repeated {"ticket":, split on }\n{)
  → _try_parse_json_string (+ json_repair)
  → pick best payload by _score_vlm_payload (product count, header fields)
  → normalize_vlm_ticket
       → coerce date, normalize names, round prices, coerce units
       → _dedupe_vlm_products (exact nom + prix + unites)
  → ReceiptParser / extract_receipt output (README schema)
```

#### Duplicate rule

Two products are merged only when **all three** match after normalization:

- `nom_produit` (whitespace collapsed)
- `prix_unitaire_ou_kg` (rounded to 2 decimals)
- `unites`

Same name with different price or quantity stays as separate lines.

#### How to verify

```powershell
$env:PYTHONPATH = "src"
python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg
pytest tests/test_vlm_parse.py --no-integration
```

Expected on `4PQOWWaPoa.jpg`: 5 unique products, no repeated raisin line, valid JSON on stdout.

#### References

- Groq provider setup: Entry 7 in this file
- Append further changelog chunks: `python scripts/add_entry_to_documentation.py --file documentation/entries/<name>.md`

---

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
