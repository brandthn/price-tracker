# receipt_ocr

Extract structured data from photos of **French supermarket receipts**
(*tickets de caisse*) using OCR.

The package uses the **Strategy pattern**: OCR backends (PaddleOCR today;
Tesseract, EasyOCR stubs; Paddle, ppocrv4, and VLM backends) are interchangeable; parsing is
backend-agnostic.

```python
from receipt_ocr import extract_receipt

data = extract_receipt("data/raw/images_tickets_caisse/4PQOWWaPoa.jpg")
```

Output schema ([`project_guidelines.md`](project_guidelines.md)):

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

Implementation history and performance notes: [`documentation.md`](documentation.md).

---

## Project layout

```
src/receipt_ocr/
├── __init__.py               # extract_receipt, reset_default_backend, …
├── extract_receipt.py        # public API + cached backend factory
├── parser.py                 # ReceiptParser (multi-line French receipts)
├── constants.py              # schema enums, env var names
├── exceptions.py             # OcrBackendError, ReceiptParseError, …
└── backends/
    ├── base.py               # OcrBackend ABC
    ├── paddle_backend.py     # PaddleOCR 3.x (default, production-ready)
    ├── tesseract_backend.py  # stub
    ├── easyocr_backend.py    # stub
    └── vlm_backend.py        # stub

tests/
├── test_parser.py
├── test_extract_receipt.py
├── test_paddle_backend.py
├── test_integration_real_images.py
└── fixtures/
    ├── sample_texts.py       # synthetic OCR strings (fast unit tests)
    └── super_u_ocr_text.py   # real OCR layout from 4PQOWWaPoa.jpg

scripts/
├── download_datasets.py      # HuggingFace + Kaggle (idempotent)
└── smoke_test_ocr.py         # one-image OCR smoke test with timings

data/raw/
├── images_tickets_caisse/    # local receipt photos
└── ocr_testing/              # dataset references

conftest.py                   # pytest: integration markers, image limits
pyproject.toml
requirements.txt
documentation.md              # versioned changelog / design notes
```

---

## Installation

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

| Package | Role |
|---------|------|
| `paddleocr` + `paddlepaddle` | Default OCR backend |
| `Pillow` | Image downscaling before OCR |
| `pytest` | Tests |
| `huggingface_hub`, `kagglehub` | Optional dataset download |

**Unit tests only** (no OCR installed):

```bash
pip install pytest
pytest --no-integration
```

---

## Usage

### Single image (recommended first try)

```bash
# From repo root — set PYTHONPATH so the package imports without pip install -e .
$env:PYTHONPATH = "src"                                    # PowerShell
# export PYTHONPATH=src                                     # bash

python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg
```

Options:

| Flag / env | Effect |
|------------|--------|
| `--raw-only` | Print OCR text only (skip parser) |
| `RECEIPT_OCR_CPU_THREADS` | Max CPU threads (default `2`) |
| `RECEIPT_OCR_MAX_IMAGE_SIDE` | Resize longest side in px (default `1280`) |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | Skip slow PaddleX host check (set automatically in code) |

**Expect ~30–40 s** for first model load, then **~1–2 min per large photo** on CPU. That is normal; the machine should stay responsive (no full freeze) with default settings.

### Test script (`extract_receipt` import + full pipeline)

```bash
$env:PYTHONPATH = "src"
python scripts/test_extract_receipt.py
python scripts/test_extract_receipt.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg --backend ppocrv4
```

The script imports `extract_receipt` from `receipt_ocr`, runs it on one image, validates the JSON schema, and prints the result.

### Python API

```python
from receipt_ocr import extract_receipt

# Default backend (PaddleOCR) is created once and cached.
data = extract_receipt("ticket.jpg")
```

**Batch processing** — create the backend once:

```python
from receipt_ocr.backends import PaddleOcrBackend
from receipt_ocr import extract_receipt

backend = PaddleOcrBackend()
for path in image_paths:
    data = extract_receipt(path, backend=backend)
```

### Backend selection

```python
from receipt_ocr.backends import PaddleOcrBackend
from receipt_ocr import extract_receipt

backend = PaddleOcrBackend(lang="fr")
data = extract_receipt("ticket.jpg", backend=backend)
```

Or via environment variable:

```bash
RECEIPT_OCR_BACKEND=paddle python my_script.py
```

Valid values: `paddle` (default), `ppocrv4` (fast mobile PP-OCRv4 path), `vlm` (Moondream VLM), `tesseract`, `easyocr` (last two are stubs).

```bash
RECEIPT_OCR_BACKEND=ppocrv4 python scripts/smoke_test_ocr.py
```

### Reset cached backend (tests)

```python
from receipt_ocr import reset_default_backend

reset_default_backend()
```

---

## PaddleOCR backend (defaults)

Tuned for **Windows laptops** without freezing the system:

| Default | Value | Reason |
|---------|-------|--------|
| Engine | `paddle_dynamic` | `paddle_static` + oneDNN often crashes on Windows |
| Mobile det models | **off** | Mobile weights require `paddle_static` |
| Max image side | `1280` px | Faster OCR on phone photos |
| CPU threads | `2` | Avoid pegging all cores |
| MKL-DNN | off | Stability on Windows |
| Preprocessing | doc orientation / unwarping / textline orientation **off** | Speed |

Optional lighter detection (Linux / when `paddle_static` works):

```python
PaddleOcrBackend(use_mobile_models=True)  # PP-OCRv4_mobile_det + paddle_static
```

---

## VLM backend (Moondream 0.5B)

Vision-Language backend for experimentation. Switch models via `RECEIPT_VLM_MODEL` without changing application code.

```bash
pip install -r requirements-vlm.txt
# Download moondream-0_5b-int8.mf (~593 MiB) from https://moondream.ai/
# Place in data/models/ or set RECEIPT_VLM_MODEL_PATH

RECEIPT_OCR_BACKEND=vlm python scripts/test_extract_receipt.py ticket.jpg --backend vlm
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECEIPT_VLM_MODEL` | `moondream-0.5b` | Provider registry id |
| `RECEIPT_VLM_MODEL_PATH` | — | Path to local `.mf` weights |
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1024` | Resize before inference |
| `MOONDREAM_API_KEY` | — | Cloud API if no local weights |

Inject a custom provider in code:

```python
from receipt_ocr.backends.vlm import build_vlm_provider
from receipt_ocr.backends.vlm_backend import VlmBackend

backend = VlmBackend(provider=build_vlm_provider("moondream-0.5b"))
```

---

## Parser capabilities

`ReceiptParser` handles typical French ticket quirks:

- Header: chain + address (no hardcoded brand list)
- Date: `DD/MM/YYYY HH:MM` and **split lines** (`15/10/24` then `12:40`)
- Products: same-line `NAME 1,20 €`, or **multi-line** (name → unit price → total → `2 x`)
- Weight: `0,452 kg x 5,98 €/kg` and multi-line per-kg blocks
- Footer: totals, TVA, payment lines ignored

---

## Downloading test datasets

```bash
python scripts/download_datasets.py
```

Reads [`data/raw/ocr_testing/datasets_to_use_for_testing.txt`](data/raw/ocr_testing/datasets_to_use_for_testing.txt):

- HuggingFace: `shirastromer/supermarket-receipts`
- Kaggle: `sushmithanarayan/expenses-receipt-ocr`

| Flag | Effect |
|------|--------|
| `--source-list` | Override list file path |
| `--target` | Override download root |
| `--force` | Re-download even if present |
| `-v` | Verbose logging |

---

## Running tests

```bash
# Fast unit tests — no network, no OCR, no real images (~1 s)
pytest --no-integration

# Integration: OCR up to 3 images in images_tickets_caisse/ (slow)
pytest -m integration

# More local images
pytest -m integration --integration-max-images 10

# Include Kaggle cache (hundreds of images — not for laptops)
pytest -m integration --integration-all-data --integration-max-images 0

# Skip integration entirely
pytest --no-integration
```

Integration tests use a **session-scoped** `PaddleOcrBackend` (one model load per run).

---

## Adding a new backend

1. Create `src/receipt_ocr/backends/<name>_backend.py`.
2. Subclass `OcrBackend`, implement `extract_text(self, image_path) -> str`.
   - Import third-party libs **inside** `__init__`.
   - Wrap errors in `OcrBackendError`.
3. Register in `extract_receipt.py` → `_BACKEND_REGISTRY`.
4. Add mocked unit tests (see `tests/test_paddle_backend.py`).

The parser and `extract_receipt()` API stay unchanged.

---

## Design notes

- **No hardcoded supermarket names** — chain inferred from OCR header.
- **Custom exceptions** — `OcrBackendError`, `ReceiptParseError`.
- **Lazy OCR imports** — `import receipt_ocr` works without Paddle installed.
- **Cached default backend** — avoids reloading multi-GB models on every call.
- **Changelog** — see [`documentation.md`](documentation.md) for versioned entries (initial build, performance work, real-receipt validation).
