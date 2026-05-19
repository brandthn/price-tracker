# receipt_ocr

Extract structured data from photos of **French supermarket receipts**
(*tickets de caisse*) using OCR.

The package is built around the **Strategy pattern** so that different
OCR backends (PaddleOCR, Tesseract, EasyOCR, vision-language models, …)
can be swapped in with zero code changes.

```python
from receipt_ocr import extract_receipt

data = extract_receipt("data/raw/images_tickets_caisse/IMG_0001.jpg")
```

The returned dict matches the schema described in
[`project_guidelines.md`](project_guidelines.md):

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

---

## Project layout

```
src/receipt_ocr/
├── __init__.py
├── extract_receipt.py        # public entry point + backend factory
├── parser.py                 # ReceiptParser: raw text → structured dict
├── constants.py              # field names, env-variable name, date format
├── exceptions.py             # custom exception hierarchy
└── backends/
    ├── base.py               # OcrBackend ABC
    ├── paddle_backend.py     # working PaddleOCR implementation
    ├── tesseract_backend.py  # stub
    ├── easyocr_backend.py    # stub
    └── vlm_backend.py        # stub

tests/                        # pytest unit + integration tests
scripts/download_datasets.py  # idempotent dataset downloader
data/raw/                     # real receipt images (gitignored by default)
```

---

## Installation

```bash
# (Recommended) create a virtual environment first
python -m venv .venv && source .venv/bin/activate     # Linux/macOS
# .venv\Scripts\Activate.ps1                          # Windows PowerShell

pip install -r requirements.txt
```

> **Heads-up:** PaddleOCR drags in `paddlepaddle`, which is a large
> wheel. If you only want to run the unit tests, no OCR library is
> required at all — `pip install pytest` is enough.

For development without any OCR engine installed:

```bash
pip install pytest
pytest
```

---

## Usage

### Default (PaddleOCR)

```python
from receipt_ocr import extract_receipt

data = extract_receipt("ticket.jpg")
```

### Switching backends

#### …via constructor

```python
from receipt_ocr import extract_receipt
from receipt_ocr.backends import PaddleOcrBackend

backend = PaddleOcrBackend(lang="fr", use_angle_cls=True)
data = extract_receipt("ticket.jpg", backend=backend)
```

#### …via the `RECEIPT_OCR_BACKEND` environment variable

```bash
RECEIPT_OCR_BACKEND=tesseract python my_script.py
```

Valid values: `paddle` (default), `tesseract`, `easyocr`, `vlm`.

---

## Downloading the test datasets

The datasets used to validate real-world performance are referenced in
[`data/raw/ocr_testing/datasets_to_use_for_testing.txt`](data/raw/ocr_testing/datasets_to_use_for_testing.txt).
The helper script is idempotent — it will skip anything already on
disk:

```bash
python scripts/download_datasets.py
```

Options:

| Flag             | Effect                                                  |
|------------------|---------------------------------------------------------|
| `--source-list`  | Override the path to the list file.                      |
| `--target`       | Override the destination root (default `data/raw/`).     |
| `--force`        | Re-download even if the target folder already exists.    |
| `-v / --verbose` | Verbose logging.                                         |

---

## Running the tests

```bash
# Fast unit tests only — no network, no real images required
pytest

# Include integration tests over real images on disk
pytest -m integration

# Force-skip integration tests even if images are present
pytest --no-integration
```

Integration tests are **auto-skipped** when `data/raw/` is empty, so the
default `pytest` run is always green.

---

## Adding a new backend

1. Create `src/receipt_ocr/backends/<my_backend>.py`.
2. Subclass `OcrBackend` and implement `extract_text(self, image_path) -> str`.
   * Import any third-party dependency **inside the class**.
   * Wrap engine errors in `OcrBackendError`.
3. Register it in `extract_receipt.py`:

   ```python
   _BACKEND_REGISTRY[BackendName.MY_BACKEND] = MyBackend
   ```

4. Add a unit test that mocks the third-party library (see
   `tests/test_paddle_backend.py` for a template).

That's it — the parser, public API, env-variable switch and CLI all
work unchanged.

---

## Design notes

* **No hardcoded chain names.** The parser infers the supermarket
  name from the first non-noise header line, so any chain works.
* **Custom exceptions** (`OcrBackendError`, `ReceiptParseError`) hide
  the third-party library a user happens to be running behind.
* **Lazy backend imports** mean `import receipt_ocr` succeeds even
  when no OCR library is installed.
* **Unit tests** use string fixtures so the suite runs in milliseconds
  with zero network and zero file-system dependencies.
