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

---
