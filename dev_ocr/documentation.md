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

## Version 0.2.0 (unreleased)

### Entry 11 — 2026-06-11 00:30 (UTC+2)

**Scope:** Implement the hybrid **receipt VLM** (~457M params: frozen CLIP ViT-B/16 + from-scratch multimodal projector + frozen SmolLM2-360M with hand-rolled LoRA + grammar-constrained JSON decoding) per [`documentation/receipt_vlm_spec_adapted.md`](documentation/receipt_vlm_spec_adapted.md). Training package under `vlm_training/`; runtime integration as a third `VlmProvider` (`receipt-vlm-500m`). Phase 1 training launched.

#### Motivation

Academic deliverable (LLaVA-style architecture with original from-scratch components) that doubles as a potential local/dev extraction engine, benchmarked against the production Groq baseline. The adapted spec re-anchors the original draft to this codebase: the model is trained to emit the **canonical schema** directly (`{"ticket": {date, chaine_supermarche, adresse, produits[]}}`, date `yyyyMMdd HH:mm`), so `vlm_parse` / `vlm_validate` / the retry loop in `extraction.py` work unchanged, and `workers/ocr` needs zero changes.

#### Architecture

```text
Receipt image (224×224, CLIP-normalized)
  → CLIP ViT-B/16 (frozen, ~86M)                    → (B, 197, 768)
  → MultimodalProjector (FROM SCRATCH, ~6.8M)       → (B, 32, 960)
      cross-attention w/ 32 learned query tokens + residual MLP summary
  → SmolLM2-360M-Instruct (frozen, ~360M)
      + LoRA rank 16 on every q_proj/v_proj (FROM SCRATCH, ~4M, no peft)
  → JSON-constrained decoding (FROM SCRATCH, 0 params)
      character-level grammar acceptor + lazy token masking
      → guaranteed-valid canonical JSON
```

Two deliberate deviations from the draft spec (justified in the adapted spec §1):

- **SmolLM2-360M** (`lang_dim=960`) instead of SmolLM-1.7B — the draft's "~500M total" only holds with the smaller decoder.
- **No trained `json_head.py`** — replaced by the constrained decoder: a trained head cannot *guarantee* valid JSON; the token-mask state machine does, deterministically.
- Input is **224×224** (not the draft's 448) — 448 on ViT-B/16 would yield 785 patches and break the frozen positional embeddings.

#### What was implemented — training side (`vlm_training/`, new)

| Component | File | Role |
|-----------|------|------|
| LoRA | `receipt_vlm/models/lora.py` | `LoRALinear` (zero-init delta), `inject_lora`, `merge_lora`, `count_trainable_params` |
| Projector | `receipt_vlm/models/projector.py` | `MultimodalProjector` 768→960, 32 query tokens |
| Constrained decoding | `receipt_vlm/models/constrained.py` | `CanonicalJsonStateMachine` (char-level grammar: fixed key order, `%.2f` prices, `unites ≥ 1`, JSON escapes) + `pick_token` (top-k probe → vocab scan → forced continuation, provably terminating) |
| Assembly | `receipt_vlm/models/vlm.py` | `ReceiptVLM`: forward w/ internal 32-token visual-prefix label masking, KV-cached constrained `generate`, merged-checkpoint export/load |
| Schema | `receipt_vlm/data/schema.py` | `Ticket`/`Product` dataclasses keyed off `receipt_ocr.constants`; **deterministic serializer** (`json.dumps` would emit `1.1`; grammar + CE target require `1.10`) |
| Synthetic data | `receipt_vlm/data/synthetic.py` | French receipt generator: 12 chains, ~50 products / 8 categories, price jitter, randomized thermal-printer layout; totals/TVA/payment **printed on image but absent from labels** (teaches the model to ignore them) |
| Augmentation | `receipt_vlm/data/augmentation.py` | Spec §4.3 pipeline (perspective, blur, elastic, shadow, JPEG) + 224×224 + CLIP normalize; `clip_normalize_pil` albumentations-free path for runtime |
| Dataset | `receipt_vlm/data/dataset.py` | `ReceiptDataset` (prompt masked at −100, target = canonical JSON + EOS), right-padding collate |
| CORD adapter | `receipt_vlm/data/cord_adapter.py` | `naver-clova-ix/cord-v2` → canonical (lossy, products only); lazy picklable image loader (no 800 decoded PILs in RAM) |
| SROIE adapter | `receipt_vlm/data/sroie_adapter.py` | Local SROIE folder → header fields only (no product annotations) |
| Real photos | `receipt_vlm/data/real_photos.py` | Pairs `data/raw/images_tickets_caisse/` with pseudo-labels; frozen `splits.json`; test split **requires** `"reviewed": true` |
| Trainer | `receipt_vlm/training/trainer.py` | Raw-PyTorch 3-phase loop: bf16/fp16 AMP, grad clip, cosine LR, budgeted constrained-generation val metrics, best-val checkpoints |
| Metrics | `receipt_vlm/utils/metrics.py` | Levenshtein/ANLS from scratch; field F1, product recall (greedy name matching, ANLS ≥ 0.7), price MAE, date EM |
| Scripts | `scripts/` | `generate_synthetic.py`, `pseudo_label.py` (Groq + review flags + split freezing), `train.py` (`--config`/`--resume`), `export_checkpoint.py` (LoRA merge → single `.pt`), `evaluate.py` (side-by-side vs Groq, §7 acceptance table) |
| Configs | `configs/` | `base.yaml` + `phase1/2/3.yaml` + `smoke.yaml` (3-phase curriculum: projector-only 3e-4×5 → +LoRA 1e-4×10 → low-LR 5e-5×5) |

#### What was implemented — runtime side (3 touches in `src/receipt_ocr`)

| File | Change |
|------|--------|
| `constants.py` | `VlmModelName.RECEIPT_VLM_500M = "receipt-vlm-500m"` |
| `backends/vlm/registry.py` | One new branch in `build_vlm_provider()` |
| `backends/vlm/receipt_vlm_provider.py` | New `ReceiptVlmProvider`: JSON-mode-only (raises `OcrBackendError` otherwise, like Groq), checkpoint from `RECEIPT_VLM_MODEL_PATH`, lazy `torch`/`receipt_vlm` imports, reuses `prepare_vlm_image`; `prompt` arg accepted but ignored (fixed-instruction model) |

Optional deps in `requirements-receipt-vlm.txt` (+ `pip install -e vlm_training`) — the base `receipt_ocr` install stays lightweight. Selection:

```bash
RECEIPT_OCR_BACKEND=vlm
RECEIPT_VLM_MODEL=receipt-vlm-500m
RECEIPT_VLM_MODE=json
RECEIPT_VLM_MODEL_PATH=/models/receipt_vlm_500m_merged.pt
```

#### Environment note (Windows dev machine)

Global `tokenizers==0.20.3` (pinned by `moondream`) is incompatible with `transformers` 4.57. Training therefore runs in `vlm_training/.venv` (created with `--system-site-packages`, overlaying `tokenizers 0.22.2` + `albumentations`; `receipt_ocr` and `receipt_vlm` installed editable). The global env is untouched, so the Moondream provider keeps working.

#### Tests

| Suite | Result |
|-------|--------|
| `vlm_training/tests/` (lora, projector, schema, constrained, synthetic, metrics, adapters) | **57 passed** |
| `vlm_training/tests/test_vlm.py` (`-m slow`, downloads CLIP + SmolLM2) | **4 passed** — incl. *untrained model emits valid canonical JSON under constrained decoding* |
| `dev_ocr/tests/` full suite (incl. 10 new `test_receipt_vlm_provider.py`) | **86 passed** |

Key grammar tests: rejects wrong key order / prose / 3-decimal prices / `unites=0` / trailing commas; accepts every canonical serialization regardless of token segmentation; forced continuation terminates from any prefix.

#### Data & training runs executed tonight

| Step | Result |
|------|--------|
| Synthetic generation | 5,000 image+label pairs in `vlm_training/data/synthetic/` (~2.5 min) |
| Groq pseudo-labelling | **18/19** real photos labelled (`data/real_labels/`); `image_19.jpg` failed validation 3× (GIFI ticket, bad date `"6/03/2026"`) — needs a manual label |
| Splits frozen | 10 train / 3 val / 5 test (locked `splits.json`) |
| Pipeline smoke test (`configs/smoke.yaml`) | Full loop OK on RTX 2070 8GB, fp16 AMP, loss 1.61→checkpoint |
| **Phase 1** (projector warmup, CORD+synthetic, 5,545 train / 314 val) | **Running** as detached process — log: `vlm_training/logs/phase1.log` |

Operational lesson: the first phase-1 launch died because the hosting shell was terminated mid-epoch (truncated traceback in the log, initially mistaken for an albumentations crash; a 800-call augmentation stress test over CORD+synthetic images showed zero failures). Relaunched via `Start-Process` (detached, survives shell exit).

#### Next steps

1. **Manual review (blocking for evaluation):** check the 5 test-split labels in `vlm_training/data/real_labels/` against the photos, fix Groq mistakes, set `"reviewed": true` in `review_status.json`. Optionally hand-label `image_19.jpg`.
2. **Phase 2** after phase 1 completes: `scripts/train.py --config configs/phase2.yaml --resume checkpoints/phase1_best.pt` (projector+LoRA, synthetic+real).
3. **Phase 3:** same with `configs/phase3.yaml --resume checkpoints/phase2_best.pt`.
4. **Export:** `scripts/export_checkpoint.py --checkpoint checkpoints/phase3_best.pt --output checkpoints/receipt_vlm_500m_merged.pt`.
5. **Evaluate vs Groq** (the go/no-go table, spec §7): `scripts/evaluate.py --checkpoint … --split test --baseline`. Targets: field F1 > 0.85, product recall > 0.90, price MAE < 0.05 €, date EM > 0.90, `vlm_validate` pass-rate > 0.80, valid-JSON rate = 1.00 (guaranteed by construction).
6. **Record results** in this file + decide production ambition (v1 recommendation: dev/eval engine only; Groq stays the production default — Cloud Run is CPU-only).
7. Possible follow-ups: SROIE local download wiring (`data.sroie_dir`), more synthetic render variants (fonts/rotated crops), constrained-decoding speedup (precomputed token→grammar transition cache) if eval latency matters.

#### Operational handbook (everything needed to resume work)

All commands below run from `dev_ocr/vlm_training/` using the venv interpreter `.venv\Scripts\python` (never the global Python — see environment note above).

##### Monitoring / restarting training

Phase 1 runs as a **detached process** (survives shell/IDE exit). Monitor:

```powershell
Get-Content logs\phase1.log -Tail 5          # epoch lines appear here
Get-Content logs\phase1.err -Tail 5          # stderr (warnings, tracebacks)
```

Expect lines like `Phase 1 | Epoch 2/5 | train 0.41 | val 0.39 | F1 0.12 | 2900s`. If the process is dead with no `Best: {...}` line at the end of the log, relaunch the same way (replace the config for later phases):

```powershell
Start-Process -FilePath "$PWD\.venv\Scripts\python.exe" `
  -ArgumentList "-u","scripts/train.py","--config","configs/phase1.yaml" `
  -WorkingDirectory $PWD -RedirectStandardOutput "$PWD\logs\phase1.log" `
  -RedirectStandardError "$PWD\logs\phase1.err" -WindowStyle Hidden -PassThru
```

There is **no mid-phase resume**: `--resume <ckpt>` loads *model weights only* (no optimizer/epoch state) and is meant for phase-to-phase chaining. If a phase dies mid-way, restart the whole phase (optionally resuming from the previous phase's checkpoint).

##### Checkpoints

- `checkpoints/phase{N}_best.pt` — best-val-loss snapshot per phase (+ sidecar `phase{N}_best.json` with the metric record). Each phase *overwrites its own name only*; the smoke run also wrote `phase1_best.pt` and is being overwritten by the real phase 1.
- Checkpoint contents: `{model_state, config, record}` (training format). The runtime provider does **not** read these — it needs the *merged* export (step 4 below).
- Everything under `checkpoints/`, `data/`, `logs/`, `.venv/` is gitignored.

##### Full command sequence (phases 2 → eval)

```powershell
# after phase 1 finishes (check "Best:" in logs\phase1.log)
.venv\Scripts\python scripts/train.py --config configs/phase2.yaml --resume checkpoints/phase1_best.pt
.venv\Scripts\python scripts/train.py --config configs/phase3.yaml --resume checkpoints/phase2_best.pt
.venv\Scripts\python scripts/export_checkpoint.py --checkpoint checkpoints/phase3_best.pt --output checkpoints/receipt_vlm_500m_merged.pt
.venv\Scripts\python scripts/evaluate.py --checkpoint checkpoints/receipt_vlm_500m_merged.pt `
  --images ../data/raw/images_tickets_caisse --labels data/real_labels --split test --baseline `
  --output logs/eval_results.json
```

(For long phases, prefer the `Start-Process` pattern above with `logs\phase2.log` etc.)

##### Label review workflow (blocking for evaluation)

Test split (from frozen `data/real_labels/splits.json`): `image_8, image_11, image_13, image_15, image_16`. For each:

1. Open the photo in `../data/raw/images_tickets_caisse/` next to `data/real_labels/<stem>.json`.
2. Fix any Groq mistakes directly in the JSON (keep the canonical shape: `date` as `yyyyMMdd HH:mm` or `""`, prices with 2 decimals, `unites` integer ≥ 1).
3. In `data/real_labels/review_status.json`, set `"image_X.jpg": {"reviewed": true}`.

`evaluate.py` (and `load_real_samples(split="test")`) silently drop unreviewed test images — an empty test set means flags were not set. Reviewing train/val labels is optional but improves phases 2–3.

**`image_19.jpg` caveat:** it failed pseudo-labelling, so it is in **no split** (splits froze over the 18 labelled images). To use it: hand-write `data/real_labels/image_19.json`, add the filename to one split array in `splits.json` (test recommended — it is hand-labelled by definition), and add its review flag. Do not otherwise edit frozen splits.

##### Config semantics & tuning knobs

- `train.py` merges `configs/base.yaml` ← phase file (one level deep: nested dicts like `data:` are updated key-by-key, scalars replaced).
- Current defaults are sized for the local **RTX 2070 8GB**: `batch_size: 4`, `num_workers: 0` (Windows), fp16 AMP via GradScaler (bf16 auto-selected where supported). On Colab T4/A100: raise `batch_size` to 8–16, `num_workers: 2`.
- `max_gen_samples` caps the constrained-generation val metric (it is sequential and slow on an untrained model — keep small in phase 1, raise in phase 3).
- `data.synthetic_limit` caps synthetic samples (used by `configs/smoke.yaml`); `data.sroie_dir: null` means SROIE is skipped (no local copy present).
- `configs/smoke.yaml` re-validates the whole pipeline in ~6 min after any change to models/data code: `.venv\Scripts\python scripts/train.py --config configs/smoke.yaml`.

##### Invariants to preserve when touching code

- **Prompt coupling:** `ReceiptDataset` trains with `SYSTEM_PROMPT` from `receipt_vlm/models/vlm.py`; `ReceiptVLM.generate` and the runtime provider use the same constant. Changing the prompt invalidates trained checkpoints.
- **Serializer ↔ grammar coupling:** `serialize_ticket` output must always be accepted by `CanonicalJsonStateMachine` (tested in `test_synthetic.py` / `test_constrained.py`). Any schema change must update both + the runtime `vlm_parse` expectations.
- **Dependency direction:** `vlm_training` may import `receipt_ocr`; the only permitted reverse import is the lazy one inside `receipt_vlm_provider.py`.
- Runtime tests: `python -m pytest tests -q` from `dev_ocr/` (86 incl. provider guardrails); training tests: `.venv\Scripts\python -m pytest tests -q -m "not slow"` from `vlm_training/` (57), `-m slow` for the 4 model-download smoke tests.

##### Acceptance / go-no-go

Targets (spec §7, evaluated by `scripts/evaluate.py` on the reviewed test split, vs the Groq baseline): field F1 > 0.85 · product recall > 0.90 · price MAE < 0.05 € · date EM > 0.90 · ANLS > 0.80 · `vlm_validate` pass-rate > 0.80 · valid-JSON rate = 1.00 (structural guarantee). Record the printed table in this file as a new entry, then decide v1 posture (recommendation: dev/eval engine; Groq stays production default — Cloud Run is CPU-only).

#### References

- Adapted spec: [`documentation/receipt_vlm_spec_adapted.md`](documentation/receipt_vlm_spec_adapted.md) (decisions §1, integration contract §2, acceptance §7)
- Original draft: [`documentation/receipt_vlm_spec.md`](documentation/receipt_vlm_spec.md)
- Training guide: [`vlm_training/README.md`](vlm_training/README.md)
- Provider pattern: Entries 5 and 7 in this file

---

### Entry 12 — 2026-06-11 01:00 (UTC+2)

**Scope:** Resume development from Entry 11 — richer synthetic data, practical local training pipeline, label-review tooling. Full `phase1.yaml` run had **not completed** (log stopped after startup; only smoke-test `phase1_best.json` existed).

#### Synthetic data — layout & capture variety

Extended `receipt_vlm/data/synthetic.py`:

| Capability | Detail |
|------------|--------|
| **8 layout styles** | `thermal_classic/narrow/wide`, `compact`, `retail_dashed`, `discount`, `minimal`, `dense` |
| **10 colour palettes** | cream, aged thermal, pink thermal, sepia, blue fade, etc. |
| **Pre-render noise** | vertical fade, line jitter, ghost/smear lines, optional proportional fonts |
| **Post-render distortions** | rotation, perspective warp, brightness/contrast, blur, Gaussian noise, JPEG recompression, vignette, table background framing, partial crop |
| **CLI flags** | `--diverse`, `--distort`, `--distort-intensity light\|medium\|heavy`, `--start-index` |

Generated **100 varied previews** in `vlm_training/data/synthetic_preview_varied/` (`--n 100 --diverse --distort --distort-intensity heavy`).

#### Training pipeline improvements

| Change | File | Why |
|--------|------|-----|
| On-the-fly synthetic | `receipt_vlm/data/samples.py` | Renders diverse+distorted receipts at `__getitem__` time — no 5k×PNG duplication, new layout every epoch |
| Sample builder extracted | `samples.py` ← `train.py` | `build_samples()`, `build_live_synthetic_samples()`, `load_disk_synthetic_samples()` |
| Skip slow val generation | `trainer.py` | `max_gen_samples: 0` skips constrained decoding in validation (saves ~minutes/epoch in phase 1) |
| Batch progress | `trainer.py` | `log_every: N` prints batch loss during long epochs |
| Gradient checkpointing | `vlm.py` + config | `model.gradient_checkpointing: true` — fits 8 GB VRAM |
| Label review helper | `scripts/review_labels.py` | `--list test`, `--mark-reviewed`, `--mark-all-test` |

New **local curriculum configs** (RTX 2070 8 GB, ~2–8 h total):

| Config | Epochs | Sources | Notes |
|--------|--------|---------|-------|
| `phase1_local.yaml` | 3 | CORD 150 + 1200 live synthetic | projector only, `max_gen_samples: 0` |
| `phase2_local.yaml` | 5 | 1500 live synthetic + 10 real train | + LoRA, `max_gen_samples: 8` |
| `phase3_local.yaml` | 3 | 800 live synthetic + real | low LR, heavy distort, `max_gen_samples: 16` |

**Local command sequence:**

```powershell
cd dev_ocr/vlm_training
.venv\Scripts\python scripts/train.py --config configs/phase1_local.yaml
.venv\Scripts\python scripts/train.py --config configs/phase2_local.yaml --resume checkpoints/phase1_best.pt
.venv\Scripts\python scripts/train.py --config configs/phase3_local.yaml --resume checkpoints/phase2_best.pt
.venv\Scripts\python scripts/export_checkpoint.py --checkpoint checkpoints/phase3_best.pt --output checkpoints/receipt_vlm_500m_merged.pt
# after reviewing test labels:
.venv\Scripts\python scripts/evaluate.py --checkpoint checkpoints/receipt_vlm_500m_merged.pt `
  --images ../data/raw/images_tickets_caisse --labels data/real_labels --split test --baseline
```

Review test labels before evaluate:

```powershell
.venv\Scripts\python scripts/review_labels.py --list test
# fix JSONs, then:
.venv\Scripts\python scripts/review_labels.py --mark-reviewed image_8.jpg image_11.jpg ...
```

#### Status vs Entry 11 next steps

| Step | Status |
|------|--------|
| 5k static synthetic | Done (`data/synthetic/`) |
| 100 varied previews | Done (`data/synthetic_preview_varied/`) |
| Groq pseudo-labels 18/19 | Done; `image_19.jpg` still unlabelled |
| Test label manual review | **Pending** (all `reviewed: false`) |
| Phase 1 full (`phase1.yaml`) | **Not completed** — use `phase1_local.yaml` instead |
| Phases 2–3 / export / eval | Blocked on phase 1 checkpoint |

#### Next steps

1. Run `phase1_local.yaml` → `phase2_local.yaml` → `phase3_local.yaml` (detached `Start-Process` if long).
2. Review 5 test-split labels; run `evaluate.py --baseline`.
3. Append eval results here as Entry 13.
4. Optional: full-scale run on Colab (`phase1/2/3.yaml` with `synthetic_on_the_fly: true` to save disk).

#### References

- Entry 11 operational handbook (same file)
- Varied synthetic CLI: `scripts/generate_synthetic.py --help`

---

### Entry 13 — 2026-06-11 (UTC+2)

**Scope:** Google Colab training setup — notebook, path configs, data-packaging script, config merge in `train.py`, and operator guide. Enables the full 3-phase curriculum on a T4/A100 with checkpoints persisted to Drive (alternative to local RTX 2070 runs from Entry 12).

#### Motivation

Local phase 1 on an 8 GB RTX 2070 is slow (~hours per phase) and was interrupted once by shell exit. Colab offers a free/cheap GPU, more VRAM headroom, and Drive persistence across session disconnects. The setup avoids uploading 5k synthetic PNGs by reusing on-the-fly diverse synthetic from Entry 12.

#### What was implemented

| Component | Path | Role |
|-----------|------|------|
| Config merge | `scripts/train.py` | `load_config()` merges `base.yaml` ← `colab_paths.yaml` ← `phase*_colab.yaml` when the phase filename contains `_colab` |
| Colab paths overlay | `configs/colab_paths.yaml` | Drive checkpoint dir, `batch_size: 8`, `num_workers: 2`, on-the-fly synthetic defaults, real-photo paths on Drive |
| Phase configs | `configs/phase{1,2,3}_colab.yaml` | Phase-specific LR/epochs/sources; phase 1 skips slow val gen (`max_gen_samples: 0`) |
| Notebook | `notebooks/train_receipt_vlm_colab.ipynb` | Mount Drive → clone repo → install → unzip data → train phases 1→3 → export merged `.pt` → optional sanity check |
| Operator guide | `vlm_training/COLAB.md` | Step-by-step, Drive layout, CLI equivalents, troubleshooting, time estimates |
| Data packager | `scripts/zip_colab_upload.py` | Zips `images_tickets_caisse/` + `real_labels/` → `colab_upload/receipt_vlm_colab_data.zip` for Drive upload (phases 2–3 only) |
| Gitignore | `dev_ocr/.gitignore` | `vlm_training/colab_upload/` (generated zip, not committed) |

#### Config merge order

```text
base.yaml
  ← colab_paths.yaml   (only when config name contains "_colab")
  ← phaseN_colab.yaml
```

Key Colab defaults from `colab_paths.yaml`:

| Setting | Value |
|---------|-------|
| `checkpoint_dir` | `/content/drive/MyDrive/receipt_vlm/checkpoints` |
| `batch_size` | 8 |
| `synthetic_on_the_fly` | true (3000–4000 samples, diverse + medium distort) |
| `real_images_dir` / `real_labels_dir` | under `My Drive/receipt_vlm/` |

Phase 1 needs **no** real photos (CORD + live synthetic). Phases 2–3 require the data zip or manual upload of photos + labels.

#### Expected Drive layout (after notebook run)

```text
My Drive/receipt_vlm/
├── checkpoints/
│   ├── phase1_best.pt
│   ├── phase2_best.pt
│   └── phase3_best.pt
├── images_tickets_caisse/
├── real_labels/
└── receipt_vlm_500m_merged.pt    ← download for local inference
```

#### Current state (at time of writing)

| Item | Status |
|------|--------|
| Colab notebook, configs, `COLAB.md`, zip script | **Done** |
| Entry 13 in this file | **Done** |
| Local phase 1 | **Stopped after startup** (`logs/phase1.log` shows config + sample count only — no epoch lines) |
| Colab data zip | **Not created** — local disk full (`SQLITE_FULL`) |
| Test labels | All still `reviewed: false` in `review_status.json` |

Local training cannot resume until disk space is freed. **Colab is the recommended path.**

#### Todo — Colab training path

##### 1. Free local disk space (optional but helpful)

Delete large generated folders no longer needed locally, e.g.:

- `vlm_training/data/synthetic/` (5k PNGs — Colab uses on-the-fly synthetic)
- `vlm_training/data/synthetic_preview_varied/` (previews only)
- `__pycache__` / old logs under `vlm_training/logs/`

##### 2. Push code to GitHub

Commit and push the Colab files (notebook, configs, `COLAB.md`, this entry, etc.) on branch `ocr_worker_module` (or your training branch).

##### 3. Upload real data to Drive (phases 2–3)

**Option A** — if disk space allows:

```powershell
cd dev_ocr\vlm_training
.venv\Scripts\python scripts\zip_colab_upload.py
```

Upload `colab_upload/receipt_vlm_colab_data.zip` to Google Drive.

**Option B** — if disk is still tight, upload these folders directly to `My Drive/receipt_vlm/`:

- `dev_ocr/data/raw/images_tickets_caisse/`
- `dev_ocr/vlm_training/data/real_labels/`

Phase 1 does **not** need real photos (CORD + on-the-fly synthetic only).

##### 4. Run Colab

1. [colab.research.google.com](https://colab.research.google.com) → **Runtime → Change runtime type → T4 GPU**
2. Upload `dev_ocr/vlm_training/notebooks/train_receipt_vlm_colab.ipynb` (or open from cloned repo)
3. Edit the **Configuration** cell:

```python
REPO_URL = "https://github.com/YOUR_USER/price-tracker.git"
REPO_BRANCH = "ocr_worker_module"
DATA_ZIP_ON_DRIVE = "/content/drive/MyDrive/receipt_vlm_colab_data.zip"  # if using zip
```

4. **Run all cells** (~3–4 h on T4)

Phase 1 runs without real photos. Phases 2–3 require the Drive data from step 3.

CLI equivalent (inside `vlm_training/` on Colab):

```bash
python scripts/train.py --config configs/phase1_colab.yaml
python scripts/train.py --config configs/phase2_colab.yaml --resume /content/drive/MyDrive/receipt_vlm/checkpoints/phase1_best.pt
python scripts/train.py --config configs/phase3_colab.yaml --resume /content/drive/MyDrive/receipt_vlm/checkpoints/phase2_best.pt
python scripts/export_checkpoint.py --checkpoint /content/drive/.../phase3_best.pt --output /content/drive/.../receipt_vlm_500m_merged.pt
```

##### 5. After training

1. Download `My Drive/receipt_vlm/receipt_vlm_500m_merged.pt` from Drive.
2. Set local inference env:

```powershell
$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODEL = "receipt-vlm-500m"
$env:RECEIPT_VLM_MODE = "json"
$env:RECEIPT_VLM_MODEL_PATH = "D:\path\to\receipt_vlm_500m_merged.pt"
```

3. Review the 5 test-split labels (blocking for evaluation):

```powershell
.venv\Scripts\python scripts\review_labels.py --list test
# fix JSONs in data/real_labels/, then:
.venv\Scripts\python scripts\review_labels.py --mark-reviewed image_8.jpg image_11.jpg image_13.jpg image_15.jpg image_16.jpg
```

4. Run eval vs Groq baseline:

```powershell
.venv\Scripts\python scripts\evaluate.py --checkpoint path\to\receipt_vlm_500m_merged.pt `
  --images ../data/raw/images_tickets_caisse --labels data/real_labels --split test --baseline `
  --output logs/eval_results.json
```

5. Append eval results as **Entry 14** in this file.

##### 6. If Colab session disconnects

Re-open the notebook, mount Drive again, and skip finished phases:

```python
RUN_PHASE_1 = False  # if phase1_best.pt exists on Drive
RUN_PHASE_2 = True
```

Checkpoints on Drive survive; Colab runtime state does not.

##### Optional

- Upload a partial local `phase1_best.pt` to `My Drive/receipt_vlm/checkpoints/` and set `RUN_PHASE_1 = False` to skip phase 1.
- Hand-label `image_19.jpg` (failed Groq pseudo-labelling) and add to a split if desired.

#### References

- Colab guide: [`vlm_training/COLAB.md`](vlm_training/COLAB.md)
- Notebook: [`vlm_training/notebooks/train_receipt_vlm_colab.ipynb`](vlm_training/notebooks/train_receipt_vlm_colab.ipynb)
- Local pipeline: Entry 12 in this file
- Architecture & acceptance: Entry 11 in this file

---

### Entry 14 — 2026-06-18 (UTC+2)

**Scope:** Training-ops hardening for the receipt VLM (durable cloud checkpoints, per-epoch snapshots + mid-phase auto-resume), a standalone merge-and-evaluate notebook that runs a checkpoint through the real `receipt_ocr` pipeline against the labelled test set, a new **Vertex AI Colab Enterprise** training path, and a **GCP deployment plan** for serving the VLM from the OCR worker. No runtime/library behaviour changed — this is training + tooling + docs.

#### Motivation

Training on free/cloud GPUs (Colab, Kaggle, Vertex) kept losing progress: ephemeral disks are wiped on idle-shutdown, and only `phaseN_best.pt` was synced, only at phase boundaries — a mid-phase stop lost every epoch since the last boundary. We also needed a fast way to package a *mid-training* checkpoint (e.g. phase 2) and exercise it through the actual OCR pipeline before training finishes, and a written plan for how the trained model would reach the deployed GCP worker.

#### What was implemented

| Area | Path | Change |
|------|------|--------|
| Per-epoch checkpoints | `vlm_training/receipt_vlm/training/trainer.py` | `train_phase` saves `phase{p}_epoch{NN}_loss{L}.pt` every epoch (keeps `phaseN_best.pt` for export); new `start_epoch` arg resumes mid-phase and fast-forwards the cosine LR schedule |
| Auto-resume | `vlm_training/scripts/train.py` | `resolve_resume()`: latest same-phase epoch snapshot (mid-phase recovery) → explicit `--resume` → last checkpoint of the previous phase; passes `start_epoch` to the trainer |
| Colab Enterprise | `vlm_training/notebooks/train_receipt_vlm_colab_enterprise.ipynb`, `vlm_training/COLAB_ENTERPRISE.md` | New training path; mounts the GCS bucket with `gcsfuse` so every checkpoint writes straight to the bucket (zero-loss on teardown). Includes a Workbench-vs-Colab-Enterprise comparison |
| Kaggle durability | `vlm_training/notebooks/train_receipt_vlm_kaggle.ipynb` | Pushes checkpoints to a durable Kaggle **Dataset** (per-epoch with `SAVE_EVERY_EPOCH`, else per-phase); restores all `phase*.pt` on resume; auth via Kaggle Secrets |
| Merge + evaluate | `vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb` | New local notebook: merge any `phase{1,2,3}` checkpoint → run the **real `receipt_ocr` pipeline** (`extract_receipt`, VLM provider) on the labelled real receipts (`load_real_samples`), printing prediction-vs-gold + the `evaluate.py` acceptance metrics |
| Deployment plan | `documentation/receipt_vlm_gcp_deployment_plan.md` | Plan to serve `receipt-vlm-500m` from `prt-prod-worker-ocr` (in-worker, L4 GPU, opt-in toggle); readiness gaps + steps + risks |
| README pointers | `vlm_training/README.md` | Links the Workbench vs Colab Enterprise paths |

#### Checkpoint naming + resume model

- Filenames embed phase, epoch (1-indexed = epochs completed), and val-loss: `phase2_epoch07_loss0.1543.pt`.
- Resume precedence in `resolve_resume()` (checked across 6 scenarios): same-phase epoch snapshot → `--resume` → previous phase's last snapshot (legacy `phaseN_best.pt` fallback). Backward-compatible: the other notebooks' `--resume phaseN_best.pt` still works.
- Checkpoints stay **adapter-only (~45 MB)**; optimizer state is not stored, so a mid-phase resume reloads weights and continues with a fresh optimizer (LR schedule fast-forwarded). All notebooks now emit per-epoch snapshots.

#### Merge-and-evaluate notebook notes

- Runs the deployed code path (`extract_receipt`), not a bypass, so the numbers reflect production behaviour.
- Defaults `REQUIRE_REVIEWED=False` because the project labels are still pseudo-labels (none marked reviewed) — otherwise the `test` split loads 0 samples.
- Must run on the project `.venv` kernel (system Python has an incompatible `tokenizers`); cell 1 warns, cell 2 runs the merge on the venv interpreter and surfaces the real error instead of an opaque `CalledProcessError`.

#### GCP deployment — readiness (summary)

The VLM is integrated in the `receipt_ocr` library, but the deployed worker is **Groq-only**. Gaps: engine wiring in `workers/ocr/pricetracker_ocr/ocr.py`, inference deps (CUDA torch + transformers + `receipt_vlm`) in the worker image, model distribution (1.8 GB `.pt` → `*-models` GCS bucket + Cloud Run volume), baked HF cache for offline cold start, L4 GPU sizing, `modules/cloud_run` GPU+volume support, and pre-existing merge-conflict markers in the worker `Dockerfile`/`config.py`/`pyproject.toml`. Full plan in [`documentation/receipt_vlm_gcp_deployment_plan.md`](documentation/receipt_vlm_gcp_deployment_plan.md).

#### Not done / still pending

- Eval results vs Groq on the reviewed test split (blocked on hand-reviewing the 5 test labels; training still in progress) — to be **Entry 15**.
- Multi-GPU (DDP) on Kaggle T4×2 considered but deferred (modest ~1.4–1.6× gain vs. the rework + NCCL / gradient-checkpointing risk).
- No deployment executed; the plan is for team review.

#### References

- Deployment plan: [`documentation/receipt_vlm_gcp_deployment_plan.md`](documentation/receipt_vlm_gcp_deployment_plan.md)
- Colab Enterprise guide: [`vlm_training/COLAB_ENTERPRISE.md`](vlm_training/COLAB_ENTERPRISE.md)
- Merge/eval notebook: [`vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb`](vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb)
- Training architecture & local pipeline: Entries 11–13 in this file

---

### Entry 15 — 2026-07-05 (UTC+2)

**Scope:** Expand the receipt VLM's **real validation data** from ~18 French-only photos to **1,875 labelled Latin-script receipts** across four public datasets, so a multilingual receipt OCR encoder (and the current model) can actually be measured. Adds a reusable `scripts/fetch_validation_data.py` + per-dataset adapters. No model/runtime change — data + tooling only.

#### Motivation

The held-out real set was 5 test receipts — too small and too French-only to trust any metric or to validate the planned multilingual/OCR-encoder direction. The fix is volume + language breadth from public receipt datasets, converted to the canonical `{"ticket": {...}}` schema so `scripts/evaluate.py` scores them unchanged.

#### What was landed (all under `dev_ocr/data/`)

| Dataset | Receipts | Split (train/val/test) | Method | Licence |
|---------|---------:|------------------------|--------|---------|
| CORD-v2 (`naver-clova-ix/cord-v2`) | 200 | — / 100 / 100 | `cord_adapter` (existing) | CC-BY (Indonesian, full line items) |
| TrainingDataPro OCR Receipts (HF) | 19 | — / 10 / 9 | **new** `trainingdatapro_adapter.py` | CC-BY-NC-ND-4.0 (non-commercial eval only) |
| ExpressExpense SRD | 128 | 71 / 19 / 38 | Groq `pseudo_label.py` (partial, see below) | MIT |
| **WildReceipt (OpenMMLab)** | **1,528** | 804 / 300 / 424 | **new** `wildreceipt_adapter.py` | research use (SDMGR/MMOCR) |
| **Total** | **1,875** | | | up from ~18 |

#### Key components

| Component | Path | Role |
|-----------|------|------|
| Fetch CLI | `vlm_training/scripts/fetch_validation_data.py` | `--datasets cord,sroie,trainingdatapro,srd_images,wildreceipt`; downloads + converts + writes canonical labels/splits/review under `data/raw/<name>` + `data/labels/<name>` |
| WildReceipt adapter | `vlm_training/receipt_vlm/data/wildreceipt_adapter.py` | maps 26 KIE classes → `Ticket`; Store/Addr/Date/Time value-classes → header fields; pairs each `Prod_item_value` box to its nearest `Prod_price_value` box on the same row (spatial y-pairing) → `produits` |
| TrainingDataPro adapter | `vlm_training/receipt_vlm/data/trainingdatapro_adapter.py` | parses CVAT `annotations.xml` boxes (shop/item/date_time text) → `Ticket` |

All adapters follow the existing `list[ReceiptSample]` convention (`receipt_vlm/data/dataset.py`); labels are `ticket.to_dict()` = `{"ticket": {...}}`, verified end-to-end through `load_real_samples`.

#### Routing insight (drove source selection)

Pseudo-labelling is the bottleneck: Groq's free tier is a **rolling 500k-token/day** window, and cleared only ~128 SRD receipts/day before throttling (retry rounds: 45 → 29 → 53 → 0 → 1). So **datasets that already ship transcribed text were preferred** (direct adapter, zero Groq) over box-only sets. WildReceipt (real per-box text + field classes, direct OpenMMLab download, **no account**) is why the 1000+ target was cleared cheaply; a box-only Roboflow set was deliberately skipped (would only re-hit the Groq wall).

#### Known limitations (per-source, don't treat as equally clean truth)

- **CORD**: Indonesian, IDR prices, no reliable store/address → strong for line-item/OCR-reading recall, weak for header fields / price-MAE-in-EUR.
- **WildReceipt**: annotation text is space-stripped (`JungleeHandtKukkad`) and dates parse ~54% (varied formats; unparseable left empty). Fine for `product_recall`/ANLS; store/address concatenate.
- **SRD**: 128/200 labelled (Groq quota); the other 72 images are on disk, resumable via `pseudo_label.py`. Pseudo-labels are provisional, not hand-reviewed.
- **Review status**: CORD/TrainingDataPro/WildReceipt are marked `reviewed=true` (dataset ground truth); SRD pseudo-labels are `reviewed=false`. `evaluate.py --split test` uses `require_reviewed=True`, so pass `require_reviewed=False` (or run `review_labels.py`) to score SRD.

#### How to use

```bash
# fetch/refresh any source (idempotent):
python scripts/fetch_validation_data.py --datasets wildreceipt
# evaluate a merged checkpoint on real receipts:
python scripts/evaluate.py --checkpoint <merged.pt> \
    --images ../data/raw/wildreceipt --labels ../data/labels/wildreceipt --split test
```

Raw images are `.gitignore`d per dataset (reproducible via the fetch script); small text labels are committable.

#### Still pending

- SRD remainder (72) — resume when Groq quota is fresher.
- Optional extra volume: Kaggle `dhiaznaidi/receiptdatasetssd300v2` (~2,901, CSV mirror has text → future `srd300_adapter.py`, no Groq). Roboflow skipped.
- Eval numbers vs Groq on this enlarged real set (still gated on a trained checkpoint) — future entry.

#### References

- Standalone entry: [`documentation/entries/2026-07-05-real-validation-data-expansion.md`](documentation/entries/2026-07-05-real-validation-data-expansion.md)
- Data loader / splits: `vlm_training/receipt_vlm/data/real_photos.py`
- Prior training-ops work: Entry 14 in this file

---

### Entry 16 — 2026-07-06 (UTC+2)

**Scope:** First end-to-end result of the **from-scratch OCR-free VLM** (`OcrVLM`, no CLIP / no
SmolLM2). M1 (READ/STRUCTURE pretraining, schema target) finished on Kaggle T4; a new eval harness
measured it on real receipts and surfaced a **total sim-to-real gap**; **Stage B** (real-data mixing)
was implemented, tested, and wired into the Kaggle notebook. Model architecture unchanged — this entry
is about *measuring* M1 and *reacting* to it.

#### Motivation

M1 trained on **synthetic only** (on-the-fly multilingual receipts, perfect labels) — by design, to
teach the encoder+decoder to read at infinite variety/zero labelling cost. But `scripts/evaluate.py`
only runs the old CLIP+SmolLM2 model, so `OcrVLM` had **no eval path** and the 1,875 real receipts
(Entry 15) had never touched it. Before spending more GPU we needed to know: does the from-scratch
stack actually read *real* photos, or only its own synthetic distribution?

#### M1 training result (Kaggle T4, schema target, 40 epochs, ~5.6 h)

Synthetic held-out eval climbed monotonically and was **still rising at epoch 40** (stopped on the
epoch cap, not converged): `product_recall` 0.02 → **0.558**, ANLS 0.32 → **0.904**, `valid` JSON
**1.00** throughout; `field_f1` 0.148 (harsh exact-whole-field match — ANLS 0.90 = strings *nearly*
right, not yet char-perfect). Checkpoint `ocr_vlm_epoch040_loss0.2265.pt` + tokenizer live in Kaggle
Dataset `giorgiopasini/receipt-ocr-vlm-checkpoints`. Read: the from-scratch stack reads+structures
synthetic and just needed more steps.

#### New eval harness — `scripts/evaluate_ocr_vlm.py`

Drives the from-scratch stack (`OcrVLM.from_checkpoint` → `prepare_ocr_pixels` → greedy `generate` →
`Ticket`), scored by the shared `evaluate_tickets`. Prints a **per-dataset + aggregate** acceptance
table plus qualitative pred-vs-gold dumps; `--synthetic N` adds a held-out synthetic sanity column.
Reuses `load_real_samples` (handles WildReceipt's nested tree, enforces `reviewed` on test). Unlike
`evaluate.py` it needs no CLIP normalization / constrained decoding.

Reviewed real **test** available: cord 100 + wildreceipt 424 + trainingdatapro 9 = **533** (SRD's 39
are unreviewed pseudo-labels → excluded unless `--include-unreviewed`).

#### The finding — total sim-to-real gap (epoch-40 checkpoint)

| Metric | Synthetic (128) | WildReceipt (424) | TrainingDataPro (9) |
|--------|----------------:|------------------:|--------------------:|
| Field F1 | 0.078 | **0.000** | 0.000 |
| Product recall | 0.357 | **0.001** | 0.000 |
| ANLS | 0.787 | **0.170** | 0.185 |

The model reads its **synthetic** domain but **fails entirely on real photos** — and not by garbling:
on every real image it emits a *valid, coherent* ticket from a handful of **memorized synthetic
stores** (Lidl/Aldi/Carrefour/Conad) with French/Italian products. Examples: real "Jungle Jamboree" →
`Carrefour Express`; real "CVS/pharmacy" → `Lidl`; real "Trader Joe's" → `Lidl`. It generates from its
synthetic prior and barely conditions on real pixels. **Not a pipeline bug** — output structure is
always valid and real/synthetic share identical preprocessing. This is the #1 risk the plan flagged.
Secondary: **date reading is broken even on synthetic** (date_accuracy 0.000 — plausible-but-wrong
dates); CORD is unusable for this EU model (empty store/date, IDR prices) and WildReceipt gold is a
harsh yardstick (space-stripped OCR names), but the store-name miss on real is unambiguous.

Consequence: **more synthetic-only epochs won't help** (they'd just sharpen the synthetic prior). The
model must *see real receipts*.

#### Stage B — real-data mixing (implemented + wired, ready to run)

`scripts/train_ocr_vlm.py` gained `--real` / `--real-repeat` / `--real-data-dir`:
`build_real_train_samples()` loads the real **train** splits that exist (wildreceipt 804 + srd 71 =
**875**), oversamples them (`--real-repeat`, default 4) and mixes them into the synthetic stream.
Schema target only (real photos have no rendered transcription — guarded); auto-resume from epoch 40
still applies. Mixed batches work because `dataset._load_image` already handles both a real `Path` and
a synthetic callable. `--real-data-dir` overrides the data base so the same code runs locally or from
an attached Kaggle Dataset (`raw/<name>` + `labels/<name>`).

`notebooks/train_ocr_vlm_kaggle.ipynb` retargeted to Stage B (schema, N=4000, EPOCHS=50 → 10 more
epochs, REAL ×4, `REAL_DATA_DIR=/kaggle/input/receipt-vlm-real-data`). Real data zipped to
`colab_upload/receipt_vlm_real_data.zip` (195 MB, wildreceipt+srd raw+labels) for upload as Kaggle
Dataset `receipt-vlm-real-data`. Code bundle rebuilt with the new trainer + eval script.

#### How to use

```bash
# measure any OcrVLM checkpoint on real + held-out synthetic (run locally on GPU):
python scripts/evaluate_ocr_vlm.py \
    --checkpoint checkpoints/ocr_vlm_epoch040_loss0.2265.pt \
    --datasets cord_v2 wildreceipt trainingdatapro --synthetic 128

# Stage B locally (real data already on disk):
python scripts/train_ocr_vlm.py --target schema --n 4000 --real --real-repeat 4 \
    --checkpoint-dir checkpoints --distort
```

Kaggle Stage B: upload the two zips (code bundle new version + `receipt-vlm-real-data`), Add Input all
three datasets (code, `receipt-ocr-vlm-checkpoints`, `receipt-vlm-real-data`), Run All → resumes at
epoch 41 and pushes checkpoints per epoch.

#### Still pending

- Run Stage B; re-eval with `evaluate_ocr_vlm.py` — the number that matters is whether **WildReceipt
  store-F1 / ANLS moves off zero**. Watch the opposite failure too: over-adapting to 875 real receipts
  and losing synthetic ANLS.
- If the gap barely moves: heavier synthetic augmentation (`--distort-intensity medium|heavy`), more
  real diversity, and the plan's reserve lever (pretrained-decoder init).
- Fix date reading (broken even on synthetic).
- Baseline comparison vs Groq + CLIP+SmolLM2 once real metrics are non-trivial (Stage C proper).

#### References

- Eval harness: `vlm_training/scripts/evaluate_ocr_vlm.py`; trainer: `vlm_training/scripts/train_ocr_vlm.py`
- Model: `vlm_training/receipt_vlm/models/{ocr_encoder,ocr_decoder,ocr_vlm}.py`
- Plan: `plans/taking-into-consideration-the-magical-feigenbaum.md` (M1/M2 sections)
- Real data: Entry 15 in this file

---

### Entry 17 — 2026-07-07 (UTC+2)

**Scope:** Ran **Stage B** (real-data mixing) end-to-end and added a **read-accuracy** metric that
finally quantifies real-photo reading. Result: the from-scratch OCR-VLM's real read-accuracy nearly
**quadrupled** (0.033 → 0.122) with no synthetic regression — real-data mixing works, now measured.
Also: an on-GPU Kaggle eval notebook (local eval OOM'd a workstation).

#### Stage B run (Kaggle T4, schema, resumed epoch 40 → 50, real ×4 + synthetic)

`mixing 3500 real (x4) + 4000 synthetic`, 875 distinct real receipts (wildreceipt 804 + srd 71).
Synthetic held-out (trainer's own eval) *improved* across the 10 epochs (ANLS 0.904 → 0.940,
product_recall 0.558 → 0.760) — no catastrophic over-adaptation to the small real set. Checkpoint
`ocr_vlm_epoch050_loss0.3619.pt`.

#### Read-accuracy metric — `score()` / `_read_accuracy()` in `evaluate_ocr_vlm.py`

The field/ANLS metrics stayed at **0** on real even as the model visibly started reading, because they
exact-match-penalize near-reads and choke on WildReceipt's space-stripped gold + foreign currency.
New metric: concatenate a ticket's readable text (store + product names, in order), normalize to
lowercase alphanumerics (drops spaces/punct/currency), and score `1 − CER` — an order-preserving,
segmentation- and currency-agnostic "did the glyphs get read" signal. Validated: correct-text/wrong-price
→ 1.0, near-read → 0.93, hallucinated store → 0.0.

#### The verdict — real reading nearly quadrupled, synthetic held

| WildReceipt (424) | epoch 40 (synth-only) | epoch 50 (Stage B) |
|-------------------|----------------------:|-------------------:|
| **Read acc (1−CER)** | **0.033** | **0.122** (×3.7) |
| ANLS | 0.170 | 0.184 |
| Field F1 / product_recall | 0.000 / 0.001 | 0.000 / 0.002 |
| Synthetic Read acc | 0.486 | 0.451 |

Epoch 40 hallucinated synthetic stores on every real image (read_acc ≈ noise); epoch 50 attempts real
reads (`WAL[UNK]MART`, `BANANAS`). **Direction validated, magnitude still small** — 0.122 = ~12% of real
characters, not enough for exact field/product matches (F1 still 0). Price MAE 32.7 on WildReceipt is a
currency artifact (rupee gold vs EU-scale reads), not error.

#### On-GPU Kaggle eval (lesson: don't eval locally)

Autoregressive `generate` over 424 receipts × 2 checkpoints pegged a local workstation (near-freeze).
Moved eval to Kaggle T4: `notebooks/eval_ocr_vlm_kaggle.ipynb` (materialize bundle → auto-locate real
data + every `ocr_vlm_epoch*.pt` → run `evaluate_ocr_vlm.py` per checkpoint). Added `--data-dir`
(attached-dataset base) + recursive `_resolve_data_base` (Kaggle nests inputs under
`/kaggle/input/datasets/<slug>/`), and made a missing dataset **skip** instead of crash. Eval checkpoints
shipped as a separate `receipt-vlm-eval-ckpts` dataset (40 + 50 + tokenizer). WildReceipt eval ≈ 8–10 min
per checkpoint on T4.

#### Still pending

- Push real read-accuracy up: more real data + more epochs, heavier synthetic augmentation
  (`--distort-intensity medium|heavy`), the pretrained-decoder reserve lever.
- A cleaner real yardstick: `trainingdatapro` (English/USD, real store names) is more interpretable than
  WildReceipt's mangled gold — add it to the uploaded eval data.
- Fix date reading (still 0.000 even on synthetic).
- Baseline comparison vs Groq + CLIP+SmolLM2 (Stage C proper).

#### References

- Eval harness + metric: `vlm_training/scripts/evaluate_ocr_vlm.py`
- Kaggle eval notebook: `vlm_training/notebooks/eval_ocr_vlm_kaggle.ipynb`
- Stage B trainer flags: `vlm_training/scripts/train_ocr_vlm.py` (`--real`/`--real-repeat`/`--real-data-dir`)
- Prior: Entry 16 in this file (Stage B setup + the sim-to-real finding)

---

### Entry 18 — 2026-07-10 (UTC+2)

**Scope:** Productionization of every `receipt_ocr` backend as its **own Cloud Run worker**
(`workers/ocr-paddle`, `ocr-ppocrv4`, `ocr-vlm-moondream`, `ocr-vlm-groq`, `ocr-vlm-receipt`,
`ocr-vlm-scratch`), with the shared pipeline extracted into a new monorepo library
`libs/pricetracker_receipt_pipeline`. **No file under `dev_ocr/` was modified** — only this
documentation. `dev_ocr` remains the research source of truth.

#### Motivation

`dev_ocr` proved that backends are interchangeable behind one parser (Strategy pattern), but only
two of them ever reached production, and both through a single worker: `workers/ocr` (tier-1, Groq)
and `workers/ocr-llm` (tier-2, Gemini). Comparing engines on real traffic meant flipping env vars on
a shared service. Splitting into one worker per backend makes each engine independently deployable,
resourced and measurable — publish the same `ticket_id` on two topics, compare the rows written.

#### What was created

| Artifact | Path | Role |
|---|---|---|
| Shared library | `libs/pricetracker_receipt_pipeline` | Frozen copy of the pipeline + the worker runtime |
| Worker (Paddle) | `workers/ocr-paddle` | `PaddleOcrBackend`, models baked into the image |
| Worker (PP-OCRv4) | `workers/ocr-ppocrv4` | `PpOcrV4MobileBackend` (+ its `paddle_backend` wrapee) |
| Worker (Moondream) | `workers/ocr-vlm-moondream` | `MoondreamProvider`, `.mf` weights from GCS |
| Worker (Groq) | `workers/ocr-vlm-groq` | `GroqProvider`, `GROQ_API_KEY` via Secret Manager |
| Worker (receipt-vlm-500m) | `workers/ocr-vlm-receipt` | `ReceiptVlmProvider`, merged `.pt` from GCS |
| Worker (from-scratch) | `workers/ocr-vlm-scratch` | **New** `OcrVlmScratchBackend` (see below) |
| Terraform | `infra/envs/prod/*_ocr_backends.tf` | 6 services, 6 topics + DLQs, 6 push subscriptions |

`tesseract` and `easyocr` were skipped: both are still `NotImplementedError` stubs.

#### The library split

`libs/pricetracker_receipt_pipeline` holds exactly what more than one worker needs, in two layers:

- **Pipeline layer** — copied verbatim from `src/receipt_ocr/` with imports rewritten
  (`receipt_ocr.` → `pricetracker_receipt_pipeline.`): `parser.py`, `constants.py`, `exceptions.py`,
  `image_utils.py`, `vlm_parse.py`, `vlm_validate.py`, `vlm_image_prep.py`, `vlm_text_cleanup.py`,
  `backends/base.py`, `backends/vlm/{base,extraction,multipass,prompts}.py`.
- **Worker runtime** (`worker/`) — lifted from `workers/ocr-llm`: OIDC auth, structlog JSON logging,
  GCS download, Pub/Sub envelope parsing, the atomic Cloud SQL write, the schema→SQL mapper, plus a
  new `weights.py` (idempotent GCS model download at startup).

Concrete backends and providers are **not** in the library. Each worker copies the one it uses, so
`paddlepaddle` never ships in the Groq image and `torch` never ships in the Paddle image.

**Two adaptations were required** (the only behavioural deltas vs `dev_ocr`):

| `dev_ocr` | Library | Why |
|---|---|---|
| `VlmBackend(provider=None, model=None, **kw)` → falls back to `build_vlm_provider()` | `VlmBackend(provider)` — required arg | No registry: each worker hardwires one backend |
| `auth.verify_oidc` reads a module-level `get_settings()` | `build_verify_oidc(get_settings)` factory | The library must not own a settings singleton |

**Deliberately not copied:** `extract_receipt.py` and `backends/vlm/registry.py` (factories — dead
weight when the backend is fixed at build time), `env.py` (`.env` loading, replaced by
pydantic-settings), the two stubs.

#### The from-scratch OCR-VLM had no provider

`OcrVLM` (Entries 16–17) lived only in `vlm_training/` and was reachable solely through
`scripts/evaluate_ocr_vlm.py` — there was no `receipt_ocr` provider for it. `workers/ocr-vlm-scratch`
therefore introduces `scratch_backend.py`, which implements `OcrBackend` **directly** rather than
going through `VlmBackend` / `VlmProvider`. That machinery exists for prompts, crop escalation and
validation-driven retries; this model has none of them — it takes no prompt and decodes the canonical
ticket deterministically. Inference mirrors the eval script:

```text
CharTokenizer.load(tokenizer.json)
  → OcrVLM.from_checkpoint(ckpt.pt, tokenizer, device="cpu")
  → prepare_ocr_pixels(image)            # letterbox 384×256, CHW float32
  → model.generate(batch)                # greedy, ≤640 char tokens
  → Ticket.to_dict()  →  json.dumps
```

The emitted JSON is already the canonical schema, so `ReceiptParser.parse_text` short-circuits
through `try_parse_vlm_json` and the heuristic parser never runs — the same path Groq and
receipt-vlm-500m take. It is the only backend needing **two** weight files (checkpoint + character
tokenizer), which is why the worker config grew `PRT_TOKENIZER_GCS_URI` alongside
`PRT_MODEL_GCS_URI`.

**Deployed checkpoint: `ocr_vlm_epoch050_loss0.3619.pt`** (Stage B), per `eval_epoch0*.json`: real
ANLS 0.183 vs 0.170 and `product_recall` doubled vs epoch040. The higher loss is the synthetic+real
mix, not a regression. Consistent with the roadmap's "current best checkpoint".

> ⚠️ Per Entry 17, loading and generating with this model **froze a local workstation**. Its worker
> tests monkeypatch the model; the checkpoint is never loaded locally. The test that exercises
> `extract_text` asserts the real `prepare_ocr_pixels` preprocessing yields a `(1, 3, 384, 256)`
> batch against a stub model. First real inference happens on Cloud Run.

#### Worker contract (identical for all six)

Same contract as `workers/ocr` / `workers/ocr-llm` — see
[`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md):

```text
Pub/Sub push {"ticket_id": "..."}  →  POST /push (OIDC)
  → SELECT gcs_path FROM tickets
  → download image from GCS bronze
  → backend.extract_text() → ReceiptParser → canonical dict
  → alias_lookup.resolve_line_eans()   (pricetracker_matching, read-only)
  → atomic tx: DELETE prix_extraits → INSERT → UPDATE tickets (ocr_attempts bumped last)
  → HTTP 204
```

| Situation | HTTP | Effect |
|---|---|---|
| Success | 204 | ACK; rows written |
| Malformed Pub/Sub envelope | 400 | ACK |
| Deterministic failure (unreadable image, invalid model output) | 204 | ACK, no retry; previous result untouched |
| Transient failure (DB, GCS 5xx, weights unreachable) | 5xx | NACK → backoff → DLQ after 5 attempts |

`GET /healthz` answers only once the lifespan completed: weights downloaded, backend constructed, PG
pool up. A worker that cannot load its model therefore never ACKs a message — Cloud Run restarts it.

#### Model weights

Local-weight backends do **not** bake weights into the image; `worker/weights.py` downloads them from
the existing models bucket on cold start (download to `<file>.part` then `os.replace`, skipped when
the local file already matches the blob size).

| Worker | `PRT_MODEL_GCS_URI` (under `gs://<project>-models/`) |
|---|---|
| `ocr-vlm-moondream` | `vlm/moondream/v1/moondream-0_5b-int8.mf` |
| `ocr-vlm-receipt` | `vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt` |
| `ocr-vlm-scratch` | `vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt` (+ `tokenizer_20260607_0900.json`) |

Exception: `ocr-vlm-receipt` **bakes the HF backbones** (CLIP ViT-B/16, SmolLM2-360M-Instruct) into
the image with `HF_HUB_OFFLINE=1`, because `ReceiptVLM.from_merged_checkpoint` calls `from_pretrained`
at load time and Cloud Run runs with `vpc_egress = PRIVATE_RANGES_ONLY` (no public internet egress).
Paddle/PP-OCRv4 likewise bake their detection/recognition models at build time.

#### Sizing

| Worker | cpu / memory / max_instances | Rationale |
|---|---|---|
| `ocr-paddle`, `ocr-ppocrv4` | 2 / 4Gi / 3 | Local CPU inference + baked models |
| `ocr-vlm-moondream` | 2 / 2Gi / 3 | int8 0.5B weights in `/tmp` (tmpfs = RAM) |
| `ocr-vlm-groq` | 1 / 1Gi / 3 | No local inference; waits on the Groq API |
| `ocr-vlm-receipt` | 4 / 16Gi / 2 | 1.8 GB checkpoint in tmpfs + fp32 CPU load peak; >8Gi requires ≥4 vCPU |
| `ocr-vlm-scratch` | 2 / 4Gi / 2 | Compact model, but greedy decode ≤640 tokens on CPU |

`timeout_seconds = 540` everywhere, below the subscriptions' `ack_deadline_seconds = 600`.

#### This supersedes the GPU deployment plan

[`receipt_vlm_gcp_deployment_plan.md`](../receipt_vlm_gcp_deployment_plan.md) (2026-06-18) proposed
running `receipt-vlm-500m` **inside** `prt-prod-worker-ocr`, on an **NVIDIA L4 GPU**, behind a
Terraform `ocr_vlm_enabled` toggle. What shipped is the alternative that document itself recorded as
"considered": a **separate service per backend**, on **CPU**, no toggle. The existing Groq path is
untouched, each engine scales and fails independently, and no GPU quota is needed. The tradeoff is
accepted latency: fp32 CPU inference for `receipt-vlm-500m`, bounded by the 540 s worker timeout and
capped at 2 instances.

#### Infrastructure — additive only

Four new files in `infra/envs/prod/`; **no existing `.tf` file was modified**:

- `variables_ocr_backends.tf` — 6 image tags (default `skeleton` = the hello image, so `apply` works
  before the first build) + 4 model-URI variables.
- `cloud_run_ocr_backends.tf` — 6 services + a **separate** `ocr_backend_worker_sa_invoker` resource
  (adding keys to the existing `worker_sa_invoker` `for_each` would have re-planned the 6 live ones).
- `pubsub_ocr_backends.tf` — a **second instantiation** of `modules/pubsub` (it only creates
  per-topic resources, so it is safe to instantiate twice) with one topic + DLQ per backend. The
  `ticket-uploaded` and `ocr-retry` routings are byte-identical.
- `subscriptions_ocr_backends.tf` — 6 push subscriptions cloning `ocr_retry_worker_push` semantics.

The single edit to an existing file is an **append** to the root `.gcloudignore`, excluding
`dev_ocr/vlm_training/{checkpoints,colab_upload,data,notebooks}/` — 4.4 GB that was being uploaded
into the build context of *every* `gcloud builds submit`, including `ocr-llm`'s. Nothing reads those
directories at build time; the inference weights travel through the models bucket.

#### Verification

65 unit tests green (28 library + 5/5/5/5/7/10 per worker); all six FastAPI apps import and expose
`/healthz` + `/push`; `terraform validate` passes. No heavy model is loaded by any test — backends
are monkeypatched, so `torch`, `paddlepaddle` and the real checkpoints stay out of the test path.

```bash
cd libs/pricetracker_receipt_pipeline && uv run pytest
cd workers/ocr-vlm-groq && uv run pytest
docker build -f workers/ocr-vlm-groq/Dockerfile -t worker-ocr-vlm-groq:dev .   # from monorepo root
```

`terraform plan` (must show only `+ create`), the image builds, the weights upload and `apply` are
the devops team's steps; each worker's `README.md` and `cloudbuild.yaml` header carries the exact
commands.

#### Impact on `dev_ocr`

None, by design. The library is a **frozen copy**, not an import of `receipt_ocr`: `dev_ocr` stays
free to evolve (new backends, parser tweaks) without a Cloud Run rollout, and the workers stay
pinned to a reviewed snapshot. The cost is that a parser fix must be **ported** to
`libs/pricetracker_receipt_pipeline` to reach production — port it there, re-run both test suites.

Note that `workers/ocr` and `workers/ocr-llm` still consume `dev_ocr` directly through
`[tool.uv.sources] receipt-ocr = { path = "../../dev_ocr" }`, and `ocr-vlm-receipt` /
`ocr-vlm-scratch` consume `dev_ocr/vlm_training` the same way (read-only, model code only).

#### References

- Worker contract: [`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md)
- Library: [`libs/pricetracker_receipt_pipeline/README.md`](../../../libs/pricetracker_receipt_pipeline/README.md)
- Superseded plan: [`receipt_vlm_gcp_deployment_plan.md`](../receipt_vlm_gcp_deployment_plan.md)
- From-scratch model: Entries 16–17 in this file, [`ocr_vlm_from_scratch_roadmap.md`](../ocr_vlm_from_scratch_roadmap.md)
- Template worker: `workers/ocr-llm/`

---
