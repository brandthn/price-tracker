**CONTEXT**

I'm building a Python module for a school project that extracts structured data from photos of French supermarket receipts (*tickets de caisse*) using OCR. The module must be production-quality, test-driven, and designed so that different OCR backends can be swapped in with minimal code changes.

---

**GOAL**

Implement a function:

```python
def extract_receipt(image_path: str) -> dict:
    ...

```

that takes the path to a receipt image and returns a dict matching this schema:

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

**ARCHITECTURE REQUIREMENTS**

Apply the **Strategy pattern** to make OCR backends interchangeable:

1. Define an abstract base class `OcrBackend` (or Protocol) with a single method: 
  ```python
  def extract_text(self, image_path: str) -> str:    ...

  ```
2. Implement a concrete class `PaddleOcrBackend(OcrBackend)` as the first backend.
3. Leave clear stubs / placeholder classes for future backends: `TesseractBackend`, `EasyOcrBackend`, `VlmBackend` — each in its own file under `backends/`.
4. Implement a `ReceiptParser` class that takes any `OcrBackend` instance and uses it to extract and structure the receipt data.
5. The top-level `extract_receipt(image_path, backend=None)` function should default to `PaddleOcrBackend` but accept any `OcrBackend`.

**Folder structure to target:**

```
src/
└── receipt_ocr/
    ├── __init__.py
    ├── extract_receipt.py        # public entry point
    ├── parser.py                 # ReceiptParser: raw text → structured dict
    └── backends/
        ├── __init__.py
        ├── base.py               # OcrBackend ABC / Protocol
        ├── paddle_backend.py
        ├── tesseract_backend.py  # stub
        ├── easyocr_backend.py    # stub
        └── vlm_backend.py        # stub

tests/
    ├── __init__.py
    ├── test_extract_receipt.py
    ├── test_parser.py
    ├── test_paddle_backend.py
    └── fixtures/
        └── sample_receipt.jpg    # placeholder — tests should still run without it using mocks

data/
└── raw/                          # real receipt images for integration/manual testing
    └── ocr_testing/
        └── datasets_to_use_for_testing.txt

scripts/
    └── download_datasets.py      # helper to fetch datasets listed in datasets_to_use_for_testing.txt

```

---

**DEVELOPMENT RULES**

- **Test-driven**: write tests before or alongside each component. Use `pytest`. Mock the OCR backend in parser tests so they are fast and deterministic.
- **Clean code**: single responsibility per class/function, meaningful names, no magic strings (use constants or enums for field names), type hints everywhere, docstrings on public interfaces.
- **Error handling**: raise descriptive custom exceptions (`OcrBackendError`, `ReceiptParseError`) rather than letting raw library exceptions bubble up.
- **Parsing logic** (in `ReceiptParser`) should handle typical French receipt quirks:
  - Date formats: `DD/MM/YYYY HH:MM` → convert to `yyyyMMdd HH:mm`
  - Products may have a quantity line (e.g. `3 x 1.29`) or a per-kg price
  - Chain name and address are usually in the header (first few lines)
  - Totals / TVA / loyalty lines at the bottom should be ignored
- **Configuration**: allow the backend to be selected via an env variable `RECEIPT_OCR_BACKEND` (`paddle` | `tesseract` | `easyocr` | `vlm`) as an alternative to passing it explicitly, so that switching backends in CI or experiments requires zero code change.

---

**TEST DATA & DATASETS**

The project already contains a file at `data/raw/ocr_testing/datasets_to_use_for_testing.txt`. Before writing any integration tests or fixtures:

1. **Read that file first** — it lists one or more online datasets (URLs, Kaggle slugs, HuggingFace repo IDs, etc.) that contain real receipt images to use for testing.
2. Write a helper script `scripts/download_datasets.py` that parses that file and downloads the referenced datasets into `data/raw/`, skipping any that are already present. This script should be idempotent.
3. **Unit tests** (in `tests/`) must never depend on those files being present — use mocks and in-memory fixtures so they always pass in CI with no network access.
4. **Integration tests** (tag them with `@pytest.mark.integration`) may load real images from `data/raw/`. They should be skipped automatically (via a `pytest` fixture or `conftest.py` marker) when the data folder is empty or when a `--no-integration` flag is passed, so that `pytest` alone runs only the fast unit tests.
5. When developing or validating the parsing logic, prioritize images from those datasets over synthetic fixtures — they represent real-world variability (fonts, layouts, lighting conditions, supermarket chains) that synthetic data cannot replicate.

---

**DELIVERABLES — produce them in this order:**

1. `src/receipt_ocr/backends/base.py` — the abstract interface
2. `src/receipt_ocr/backends/paddle_backend.py` — working PaddleOCR implementation
3. `src/receipt_ocr/backends/tesseract_backend.py`, `easyocr_backend.py`, `vlm_backend.py` — stubs with `NotImplementedError`
4. `src/receipt_ocr/parser.py` — `ReceiptParser` with full parsing logic
5. `src/receipt_ocr/extract_receipt.py` — public entry point + backend factory
6. `scripts/download_datasets.py` — dataset download helper
7. All test files with at least: happy-path test, missing-field test, wrong-image-path test, and a test that verifies swapping backends works
8. `conftest.py` at the root with the integration test marker and skip logic
9. `requirements.txt` and a brief `README.md` explaining how to run, how to download the test datasets, and how to add a new backend

---

**IMPORTANT CONSTRAINTS**

- All source code lives under `src/`, all tests under `tests/`, all real image data under `data/raw/`.
- Do not hardcode any supermarket chain names — the parser should infer them from the text.
- The module must work as a standalone importable package (`from receipt_ocr import extract_receipt`).
- Unit tests must be runnable without a real receipt image and without network access (use mocks / fixtures).
- Keep each backend's third-party import inside its own class so the package can be imported even if that library is not installed (only raise `ImportError` at instantiation time).
- Integration tests must be skipped gracefully when data is absent, never fail the suite with a `FileNotFoundError`.

