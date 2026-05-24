# Documentation — receipt_ocr

Changelog and implementation notes for the `dev_ocr` module. Each version groups one or more dated entries.

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
