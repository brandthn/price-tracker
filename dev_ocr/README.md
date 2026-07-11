# receipt_ocr

Extract structured data from photos of **French supermarket receipts**
(*tickets de caisse*) using OCR.

The package uses the **Strategy pattern**: OCR backends are interchangeable and parsing is
backend-agnostic. Working backends: **Paddle** (default), **PP-OCRv4 mobile**, and three **VLM**
providers (Moondream 0.5B, Groq Llama-4 Scout, receipt-vlm-500m). Tesseract and EasyOCR are stubs.

Each backend also runs as its own Cloud Run worker — see [Production deployment](#production-deployment).

```python
from receipt_ocr import extract_receipt

data = extract_receipt("data/raw/images_tickets_caisse/image_2.jpg")
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
├── env.py                    # loads the project .env
├── image_utils.py            # resize helper (classic OCR backends)
├── vlm_parse.py              # VLM JSON → canonical schema (parse, normalize, merge)
├── vlm_validate.py           # output quality checks (drives VLM retries)
├── vlm_image_prep.py         # crop + resize pipeline for VLMs
├── vlm_text_cleanup.py       # strip chatty prefixes from transcriptions
└── backends/
    ├── base.py               # OcrBackend ABC
    ├── paddle_backend.py     # PaddleOCR 3.x (default, production-ready)
    ├── ppocr_v4_backend.py   # PP-OCRv4 mobile (fast path, wraps paddle_backend)
    ├── tesseract_backend.py  # stub
    ├── easyocr_backend.py    # stub
    ├── vlm_backend.py        # VlmBackend → delegates to a VlmProvider
    └── vlm/
        ├── base.py               # VlmProvider ABC
        ├── registry.py           # build_vlm_provider() factory
        ├── extraction.py         # run_vlm_extraction(): modes, retries, validation
        ├── multipass.py          # 3 focused prompts merged into one ticket
        ├── prompts.py            # French prompt templates
        ├── moondream_provider.py # local Moondream 0.5B (int8 .mf)
        ├── groq_provider.py      # Groq cloud Llama-4 Scout (JSON mode)
        └── receipt_vlm_provider.py  # local CLIP+SmolLM receipt-vlm-500m

vlm_training/                 # separate package: trains receipt-vlm-500m and the
                              # from-scratch OcrVLM (see documentation/ roadmaps)

tests/
├── test_parser.py
├── test_extract_receipt.py
├── test_paddle_backend.py
├── test_integration_real_images.py
└── fixtures/
    ├── sample_texts.py       # synthetic OCR strings (fast unit tests)
    └── super_u_ocr_text.py   # real OCR layout from image_2.jpg (Super U)

scripts/
├── download_datasets.py      # HuggingFace + Kaggle (idempotent)
└── smoke_test_ocr.py         # one-image OCR smoke test with timings

data/raw/
├── images_tickets_caisse/    # local receipt photos (image_1 … image_N, see rename_manifest.json)
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

python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/image_2.jpg
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
python scripts/test_extract_receipt.py data/raw/images_tickets_caisse/image_2.jpg --backend ppocrv4
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

## VLM backend

Vision-language backends share `RECEIPT_OCR_BACKEND=vlm`. Swap providers with `RECEIPT_VLM_MODEL`.

### Groq vision (cloud, JSON receipts)

Uses [Groq](https://console.groq.com/docs/vision) `meta-llama/llama-4-scout-17b-16e-instruct` to return structured JSON matching the schema above. **Requires** `RECEIPT_VLM_MODE=json` (other modes raise an error).

```bash
pip install -r requirements-groq.txt
# Copy .env.example -> .env and set GROQ_API_KEY (or groq_key)

$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODEL = "groq-llama4-scout"
$env:RECEIPT_VLM_MODE = "json"
python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/your_ticket.jpg
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_API_KEY` / `groq_key` | — | Groq API key (loaded from `.env`) |
| `RECEIPT_GROQ_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq API model id |
| `RECEIPT_VLM_MODE` | — | Must be `json` for Groq |
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1536` | Resize before upload (keep base64 under 4MB) |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | Retry on invalid JSON |

Live API tests (not mocked):

```bash
pytest -m groq
```

### Moondream 0.5B (local)

Local Moondream 0.5B with three extraction modes. Default **`transcribe`** asks the VLM for line-by-line text, then uses `ReceiptParser`.

```bash
pip install -r requirements-vlm.txt
python scripts/download_moondream_weights.py   # -> data/models/ (gitignored)

$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODE = "transcribe"   # transcribe | json | multipass
python scripts/run_vlm_test.py data/raw/images_tickets_caisse/image_12.jpg
python scripts/benchmark_vlm.py        # compare modes on reference images
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECEIPT_VLM_MODE` | `transcribe` | `transcribe`, `json`, or `multipass` |
| `RECEIPT_VLM_MODEL` | `moondream-0.5b` | Provider registry id (`moondream-0.5b`, `groq-llama4-scout`, `receipt-vlm-500m`) |
| `RECEIPT_VLM_MODEL_PATH` | `data/models/...` | Local `.mf` weights |
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1536` | Resize before inference (`0` = off) |
| `RECEIPT_VLM_CROP` | `auto` | `auto`, `center`, or `off` |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | Retry on chatty/invalid output |
| `RECEIPT_VLM_TEMPERATURE` | `0.1` | Moondream generation temperature |
| `RECEIPT_VLM_MAX_TOKENS` | `1024` | Max tokens per query |

Inject a custom provider in code:

```python
from receipt_ocr.backends.vlm import build_vlm_provider
from receipt_ocr.backends.vlm_backend import VlmBackend

backend = VlmBackend(provider=build_vlm_provider("moondream-0.5b"))
```

### receipt-vlm-500m (local, trained here)

The hybrid CLIP+SmolLM receipt VLM trained in [`vlm_training/`](vlm_training/). Emits the canonical
JSON directly under grammar-constrained decoding, so **`RECEIPT_VLM_MODE=json` is mandatory** (other
modes raise). The `prompt` argument is accepted but ignored — the model is trained on a fixed
instruction.

```bash
pip install -r requirements-receipt-vlm.txt
pip install -e vlm_training          # the receipt_vlm package (model code)

$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODEL = "receipt-vlm-500m"
$env:RECEIPT_VLM_MODE = "json"
$env:RECEIPT_VLM_MODEL_PATH = "vlm_training/checkpoints/receipt_vlm_500m_merged.pt"
```

`RECEIPT_VLM_MODEL_PATH` must point at the **merged** checkpoint produced by
`vlm_training/scripts/export_checkpoint.py` (~1.8 GB, gitignored). Loading it pulls the CLIP and
SmolLM2 backbones from the HuggingFace Hub on first use.

> The **from-scratch** `OcrVLM` (no CLIP, no SmolLM2) is a different model and has *no* provider in
> this package — it is reached through `vlm_training/scripts/evaluate_ocr_vlm.py`, or in production
> through `workers/ocr-vlm-scratch`. See
> [`documentation/ocr_vlm_from_scratch_roadmap.md`](documentation/ocr_vlm_from_scratch_roadmap.md),
> and heed its never-run-locally warning.

---

## Parser capabilities

`ReceiptParser` handles typical French ticket quirks:

- Header: chain + address (no hardcoded brand list)
- Date: `DD/MM/YYYY HH:MM` and **split lines** (`15/10/24` then `12:40`)
- Products: same-line `NAME 1,20 €`, or **multi-line** (name → unit price → total → `2 x`)
- Weight: `0,452 kg x 5,98 €/kg` and multi-line per-kg blocks
- Footer: totals, TVA, payment lines ignored

---

## Production deployment

Since 2026-07-10, **every real backend ships as its own Cloud Run worker**. Publish a
`{"ticket_id": "..."}` message on a backend's topic and that engine processes the ticket; publish the
same id on two topics to compare engines on identical input.

| Backend (here) | Worker | Pub/Sub topic | `ocr_engine` written to SQL |
|---|---|---|---|
| `PaddleOcrBackend` | `workers/ocr-paddle` | `ocr-paddle` | `paddleocr` |
| `PpOcrV4MobileBackend` | `workers/ocr-ppocrv4` | `ocr-ppocrv4` | `ppocrv4` |
| `MoondreamProvider` | `workers/ocr-vlm-moondream` | `ocr-vlm-moondream` | `moondream-0.5b` |
| `GroqProvider` | `workers/ocr-vlm-groq` | `ocr-vlm-groq` | `groq-llama4-scout` |
| `ReceiptVlmProvider` | `workers/ocr-vlm-receipt` | `ocr-vlm-receipt` | `receipt-vlm-500m` |
| `OcrVLM` (from-scratch, `vlm_training/`) | `workers/ocr-vlm-scratch` | `ocr-vlm-scratch` | `ocr-vlm-scratch` |

`tesseract` and `easyocr` are not deployed — they are still stubs.

### Model artifacts to upload (devops handoff)

Only **three** of the six workers need weights in GCS. Paddle and PP-OCRv4 bake their models into the
image at build time, and Groq calls a remote API — there is nothing to upload for those, and nothing
to look for.

Bucket: `gs://price-tracker-prod-01-models`. The object paths are the defaults of
`infra/envs/prod/variables_ocr_backends.tf` — upload elsewhere and you must override those variables.

| Local file | → GCS object path | Size | Worker |
|---|---|---|---|
| `data/models/moondream-0_5b-int8.mf` ⚠️ *generate first* | `vlm/moondream/v1/moondream-0_5b-int8.mf` | ~600 MB | `ocr-vlm-moondream` |
| `vlm_training/checkpoints/receipt_vlm_500m_merged.pt` | `vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt` | 1.82 GB | `ocr-vlm-receipt` |
| `vlm_training/checkpoints/ocr_vlm_epoch050_loss0.3619.pt` | `vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt` | 105 MB | `ocr-vlm-scratch` |
| `vlm_training/checkpoints/tokenizer_20260607_0900.json` | `vlm/ocr-vlm-scratch/v1/tokenizer_20260607_0900.json` | 993 B | `ocr-vlm-scratch` |

The last two are a **pair**: the from-scratch checkpoint is useless without the character tokenizer
fitted alongside it. Ship them together.

> ⚠️ **The Moondream `.mf` is not in the repo.** `data/models/` is gitignored and empty on a fresh
> clone. Generate it before uploading, and upload the **decompressed `.mf`**, not the `.mf.gz`:
>
> ```bash
> python scripts/download_moondream_weights.py    # 593 MB .mf.gz from HF → data/models/*.mf
> ```

From the **monorepo root**:

```bash
gsutil cp dev_ocr/data/models/moondream-0_5b-int8.mf \
  gs://price-tracker-prod-01-models/vlm/moondream/v1/

gsutil cp dev_ocr/vlm_training/checkpoints/receipt_vlm_500m_merged.pt \
  gs://price-tracker-prod-01-models/vlm/receipt-vlm/v1/

gsutil cp dev_ocr/vlm_training/checkpoints/ocr_vlm_epoch050_loss0.3619.pt \
          dev_ocr/vlm_training/checkpoints/tokenizer_20260607_0900.json \
          gs://price-tracker-prod-01-models/vlm/ocr-vlm-scratch/v1/
```

No IAM change is needed — the worker service account already has `object_viewer` on that bucket
(`infra/envs/prod/storage.tf`). `worker-ocr-vlm-receipt` additionally needs its CLIP + SmolLM2
backbones **baked into the image**, not uploaded: Cloud Run runs `PRIVATE_RANGES_ONLY` and cannot
reach the HuggingFace Hub at cold start.

**Version by prefix, never by overwrite.** To ship a new checkpoint, upload under `v2/` and bump the
matching `*_model_gcs_uri` variable. Overwriting an object in place lets a warm instance keep serving
the old weights (`ensure_weights` skips the download on a size match) while a cold one picks up the
new ones. Details and the epoch050-vs-040 rationale: **Entry 19** in [`documentation.md`](documentation.md).

### The library is a frozen copy of this package

The code shared by those workers lives in **`libs/pricetracker_receipt_pipeline`**: the parser, the
schema constants, the exceptions, the `vlm_*` helpers, the `OcrBackend` / `VlmProvider` ABCs and the
VLM extraction orchestrator — copied from `src/receipt_ocr/` with imports rewritten
`receipt_ocr.` → `pricetracker_receipt_pipeline.`. Concrete backends are **not** in the library;
each worker carries only the one it uses, so `paddlepaddle` never ships in the Groq image.

> ⚠️ **Porting rule.** The workers do **not** import `receipt_ocr`. A fix to `parser.py`,
> `vlm_parse.py` or any other shared module here does **not** reach production until it is ported to
> `libs/pricetracker_receipt_pipeline` and both test suites are re-run. The upside of the freeze is
> that this package stays free to evolve without triggering a Cloud Run rollout.

Two intentional differences in the library, both consequences of one worker owning exactly one
backend:

| Here | In the library | Why |
|---|---|---|
| `VlmBackend(provider=None, model=None)` falls back to `build_vlm_provider()` | `VlmBackend(provider)` — required argument | No registry: the backend is fixed at build time |
| `verify_oidc` reads a module-level `get_settings()` | `build_verify_oidc(get_settings)` factory | The library must not own a settings singleton |

Not carried over: `extract_receipt.py` and `backends/vlm/registry.py` (factories, dead weight when
the backend is fixed), `env.py` (`.env` loading, replaced by pydantic-settings), and the two stubs.

Full record — motivation, worker contract, model-weight distribution, sizing and the additive
Terraform — is **Entry 18** in [`documentation.md`](documentation.md).

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

# Groq cloud VLM (live API + local receipt images)
pytest -m groq

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

To take it to production (steps 1–4 only make it usable *here*):

5. Clone `workers/ocr-vlm-groq/` — the lightest template (no local weights, no heavy deps) — into
   `workers/ocr-<name>/`: rename the package, copy your backend module in with its imports rewritten
   to `pricetracker_receipt_pipeline.`, and hardwire it in `ocr.py::build_backend()`.
6. Add the service, topic + DLQ and push subscription to `infra/envs/prod/*_ocr_backends.tf` — those
   files are additive by design, so existing workers are never re-planned.

If your backend needs local weights, do not bake them into the image: publish them to the models
bucket and reuse `pricetracker_receipt_pipeline.worker.weights.ensure_weights` from the worker's
`lifespan`, as `ocr-vlm-moondream` does. Entry 18 in [`documentation.md`](documentation.md) walks
through the whole contract.

---

## Design notes

- **No hardcoded supermarket names** — chain inferred from OCR header.
- **Custom exceptions** — `OcrBackendError`, `ReceiptParseError`.
- **Lazy OCR imports** — `import receipt_ocr` works without Paddle installed.
- **Cached default backend** — avoids reloading multi-GB models on every call.
- **Changelog** — see [`documentation.md`](documentation.md) for versioned entries (initial build, performance work, real-receipt validation).
