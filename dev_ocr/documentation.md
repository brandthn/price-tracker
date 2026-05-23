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
