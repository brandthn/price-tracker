# dev_ocr / receipt_ocr — Codebase Reference for LLM-Driven Development

**Audience:** Another LLM that will receive this document together with a target architecture spec, to produce a final implementation prompt (no need to re-scan the repo).

**Scope:** The `dev_ocr/` package (`receipt_ocr` on `PYTHONPATH=src`). The planned solution must use **`RECEIPT_OCR_BACKEND=vlm`** with provider **`groq-llama4-scout`** (`GroqProvider`).

**Version:** Reflects codebase as of 2026-05-25 (`receipt_ocr` v0.1.0).

---

## 1. What this package does

`receipt_ocr` extracts **structured data from photos of French supermarket receipts** (*tickets de caisse*). It is a **standalone, importable Python package** designed for:

- Local development and benchmarking (`dev_ocr/`)
- Future embedding in `workers/ocr/` (Cloud Run worker — see `workers/ocr/ocr-worker-contract.md` for the production contract; that worker is **not implemented yet**)

Design principles (from `project_guidelines.md`):

- **Strategy pattern:** OCR engines are interchangeable via `OcrBackend`
- **Single public entry point:** `extract_receipt(image_path) -> dict`
- **Backend-agnostic parsing:** `ReceiptParser` turns raw text *or* VLM JSON into the same output schema
- **No hardcoded supermarket names** in the heuristic parser
- **Lazy third-party imports** inside backend classes
- **Custom exceptions** instead of leaking library errors

---

## 2. Repository layout (`dev_ocr/`)

```
dev_ocr/
├── src/receipt_ocr/          # Package source (install: package-dir = src in pyproject.toml)
├── tests/                    # pytest (unit + integration + groq markers)
├── scripts/                  # Smoke / benchmark CLIs
├── data/raw/                 # Receipt images (gitignored in practice)
├── documentation/            # Design docs (this file + dated entries/)
├── conftest.py               # pytest: integration skip, groq skip, PYTHONPATH
├── pyproject.toml
├── requirements.txt          # PaddleOCR stack (default backend)
├── requirements-groq.txt     # Groq VLM only
├── requirements-vlm.txt      # Moondream local VLM
├── .env / .env.example       # API keys (repo root = dev_ocr/)
├── project_guidelines.md     # Original product spec
└── README.md                 # Human-oriented usage
```

### 2.1 Package module map

| Module | Role |
|--------|------|
| `extract_receipt.py` | Public API + `build_backend()` factory + singleton cache |
| `parser.py` | `ReceiptParser`: OCR text → dict; delegates VLM JSON to `vlm_parse` |
| `constants.py` | Schema field enums, env var names, defaults |
| `exceptions.py` | `ReceiptOcrError`, `OcrBackendError`, `ReceiptParseError` |
| `env.py` | `load_project_env()` — loads `dev_ocr/.env` via python-dotenv |
| `vlm_parse.py` | Parse/normalize/dedupe VLM JSON → canonical dict |
| `vlm_validate.py` | Quality checks driving VLM retry loop |
| `vlm_image_prep.py` | Crop + resize + JPEG temp files for VLM |
| `vlm_text_cleanup.py` | Strip chatty prefixes from transcribe mode |
| `image_utils.py` | Shared resize helper for classical OCR backends |
| `backends/base.py` | `OcrBackend` ABC — `extract_text(image_path) -> str` |
| `backends/vlm_backend.py` | `VlmBackend` — wires provider + `run_vlm_extraction` |
| `backends/vlm/` | Provider registry, prompts, extraction orchestration |
| `backends/vlm/groq_provider.py` | **Groq cloud vision (JSON only)** |
| `backends/vlm/moondream_provider.py` | Local Moondream 0.5B (transcribe/json/multipass) |
| `backends/paddle_backend.py` | Default classical OCR (production baseline) |
| `backends/ppocr_v4_backend.py` | Fast mobile PP-OCRv4 path |

---

## 3. Public API — `extract_receipt`

### 3.1 Import paths

```python
# Recommended (package root exports)
from receipt_ocr import extract_receipt, reset_default_backend

# Lower-level (custom backend injection)
from receipt_ocr.extract_receipt import build_backend
from receipt_ocr.parser import ReceiptParser
from receipt_ocr.backends.vlm import build_vlm_provider
from receipt_ocr.backends.vlm_backend import VlmBackend
```

**Runtime setup:** From `dev_ocr/` directory:

```bash
export PYTHONPATH=src   # PowerShell: $env:PYTHONPATH = "src"
```

`extract_receipt` module calls `load_project_env()` on import, so `.env` at `dev_ocr/.env` is loaded before backend construction.

### 3.2 Function signature

```python
def extract_receipt(
    image_path: str,
    backend: Optional[OcrBackend] = None,
) -> dict:
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_path` | `str` | Filesystem path to receipt image (`.jpg`, `.jpeg`, `.png`, `.webp`, etc.) |
| `backend` | `OcrBackend \| None` | If `None`, uses cached default from `build_backend()` |

### 3.3 Return type — canonical output schema

Always a **plain `dict`** (not a Pydantic model). Top-level key is always `"ticket"`.

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

**Field semantics:**

| JSON key | Type | Rules |
|----------|------|-------|
| `ticket.date` | `str` | Format `%Y%m%d %H:%M` (e.g. `"20240315 14:30"`). Empty string `""` if unknown. |
| `ticket.chaine_supermarche` | `str` | Store name from receipt header. Empty if unknown. **Not** from a hardcoded brand list. |
| `ticket.adresse` | `str` | Store address lines joined. Empty if unknown. |
| `ticket.produits` | `list[dict]` | Product lines only (no totals/TVA/payment). |
| `produits[].nom_produit` | `str` | Product label as printed. |
| `produits[].prix_unitaire_ou_kg` | `float` | Unit price or price per kg; rounded to 2 decimals. |
| `produits[].unites` | `int` | Quantity purchased; `>= 1`. For weight-priced items, this is often the weight in kg as an integer convention. |

Enums in code (`constants.py`):

- `TicketField`: `TICKET`, `DATE`, `CHAINE`, `ADRESSE`, `PRODUITS`
- `ProductField`: `NOM`, `PRIX`, `UNITES`
- `OUTPUT_DATE_FORMAT = "%Y%m%d %H:%M"`

**Important:** Example files under repo `data/ocr_output_example_*.json` use **different key names** (`supermarché`, `libellé`, etc.). Those are **not** the package schema. The worker/SQL contract may map from the canonical schema — do not assume examples match `extract_receipt` output without transformation.

### 3.4 Exceptions

| Exception | When |
|-----------|------|
| `FileNotFoundError` | `image_path` does not exist (from `OcrBackend._validate_image_path`) |
| `OcrBackendError` | OCR/VLM engine failure, missing API key, Groq size limit, unsupported VLM mode for Groq |
| `ReceiptParseError` | Empty OCR text, unparseable receipt, VLM output failed validation after all retries |

All inherit from `ReceiptOcrError`.

### 3.5 Backend selection and caching

```python
def build_backend(name: Optional[str] = None, *, force_new: bool = False) -> OcrBackend
```

Resolution order for backend **name**:

1. Explicit `name` argument
2. Env `RECEIPT_OCR_BACKEND`
3. Default: `"paddle"`

Valid `BackendName` values: `paddle`, `ppocrv4`, `tesseract`, `easyocr`, `vlm`.

**Singleton cache:** First `build_backend()` / `extract_receipt()` without explicit backend caches the instance. Call `reset_default_backend()` in tests or after env changes.

### 3.6 Groq VLM — minimal working invocation

```python
import os
from receipt_ocr import extract_receipt, reset_default_backend
from receipt_ocr.backends.vlm import build_vlm_provider
from receipt_ocr.backends.vlm_backend import VlmBackend
from receipt_ocr.constants import VlmModelName, VlmMode

os.environ["RECEIPT_OCR_BACKEND"] = "vlm"
os.environ["RECEIPT_VLM_MODEL"] = VlmModelName.GROQ_LLAMA4_SCOUT.value  # "groq-llama4-scout"
os.environ["RECEIPT_VLM_MODE"] = VlmMode.JSON.value                     # "json" — required for Groq
reset_default_backend()

# Option A: env-driven default backend
result = extract_receipt("/path/to/ticket.jpg")

# Option B: explicit backend (ignores RECEIPT_OCR_BACKEND for this call)
backend = VlmBackend(provider=build_vlm_provider("groq-llama4-scout"))
result = extract_receipt("/path/to/ticket.jpg", backend=backend)
```

CLI smoke test: `scripts/test_groq_receipt.py` sets the same env vars and prints JSON to stdout.

---

## 4. End-to-end data flow

### 4.1 Generic pipeline (all backends)

```
extract_receipt(image_path)
  └─ ReceiptParser(backend).parse(image_path)
       ├─ backend.extract_text(image_path)  → str
       └─ ReceiptParser.parse_text(text)    → dict
```

### 4.2 Groq VLM pipeline (target for new work)

```
extract_receipt(image_path)
  └─ ReceiptParser(VlmBackend).parse(image_path)
       ├─ VlmBackend.extract_text(image_path)
       │    └─ run_vlm_extraction(GroqProvider, image_path)
       │         ├─ load_vlm_mode() → must be "json"
       │         ├─ _build_attempts(): prompt + optional center crop retry
       │         ├─ GroqProvider.analyze_with_options()
       │         │    ├─ prepare_vlm_image()  # crop/resize/JPEG temp
       │         │    ├─ base64 data URL
       │         │    └─ Groq chat.completions (vision + response_format=json_object)
       │         ├─ validate_vlm_output("json", output)  # retry if invalid
       │         └─ return JSON string
       └─ ReceiptParser.parse_text(JSON string)
            └─ try_parse_vlm_json(text) → normalize_vlm_ticket() → dict
            (heuristic OCR parser is SKIPPED when JSON parses successfully)
```

ASCII overview:

```
┌─────────────┐     ┌────────────┐     ┌──────────────────┐     ┌─────────────┐
│ image_path  │────▶│ VlmBackend │────▶│ run_vlm_extract  │────▶│ JSON string │
└─────────────┘     └─────┬──────┘     └────────┬─────────┘     └──────┬──────┘
                          │                       │                      │
                          │              ┌────────▼─────────┐            │
                          │              │ GroqProvider     │            │
                          │              │ (cloud API)      │            │
                          │              └──────────────────┘            │
                          │                                              │
                          └──────────────┬───────────────────────────────┘
                                         ▼
                              ┌─────────────────────┐
                              │ ReceiptParser       │
                              │ try_parse_vlm_json  │
                              └──────────┬──────────┘
                                         ▼
                              ┌─────────────────────┐
                              │ dict { "ticket": … }│
                              └─────────────────────┘
```

---

## 5. `OcrBackend` contract

```python
class OcrBackend(ABC):
    @abstractmethod
    def extract_text(self, image_path: str) -> str:
        """Raw text OR JSON string for VlmBackend in json mode."""
```

**Convention:** Classical backends return **multi-line OCR text**. `VlmBackend` in `json` mode returns a **JSON string** (often `{"ticket": {...}}`) that `ReceiptParser.parse_text` detects and short-circuits.

Implementers must:

- Validate path via `OcrBackend._validate_image_path` (raises `FileNotFoundError`)
- Wrap third-party failures in `OcrBackendError`
- Import heavy deps inside `__init__` or method body

---

## 6. `ReceiptParser` — dual parsing paths

### 6.1 `parse(image_path)` / `parse_text(text)`

```python
class ReceiptParser:
    def __init__(self, backend: OcrBackend) -> None: ...

    def parse(self, image_path: str) -> dict: ...
    def parse_text(self, text: str) -> dict: ...
```

`parse_text` logic:

1. Reject empty text → `ReceiptParseError`
2. **`try_parse_vlm_json(text)`** — if not `None`, return normalized dict immediately
3. Else run **heuristic French receipt parser** on line-split OCR text:
   - Header: chain + address (first ~6 lines, dynamic heuristics)
   - Date: multiple regex patterns + split date/time lines
   - Products: state machine for single-line prices, multi-line name→price→qty, per-kg weight lines
   - Footer keywords (`total`, `tva`, `carte bancaire`, …) stop product extraction

**Refactoring implication:** For Groq/json mode, most quality work happens in **VLM prompts + `vlm_parse` + `vlm_validate`**, not in `parser.py` heuristics. Changing Groq output shape requires updating `vlm_parse.normalize_vlm_ticket` and prompts, not the OCR line parser.

---

## 7. VLM subsystem (detailed)

### 7.1 `VlmBackend` (`backends/vlm_backend.py`)

```python
class VlmBackend(OcrBackend):
    def __init__(
        self,
        provider: VlmProvider | None = None,
        model: str | None = None,
        **provider_kwargs: Any,
    ) -> None:
        self._provider = provider or build_vlm_provider(model, **provider_kwargs)
```

Properties: `active_model`, `active_mode`.

### 7.2 Provider registry (`backends/vlm/registry.py`)

```python
def build_vlm_provider(name: str | None = None, **kwargs: Any) -> VlmProvider
```

| Registry id (`VlmModelName`) | Class | Notes |
|------------------------------|-------|-------|
| `moondream-0.5b` (default) | `MoondreamProvider` | Local `.mf` weights; supports transcribe/json/multipass |
| `groq-llama4-scout` | `GroqProvider` | Cloud API; **json mode only** |

Resolution: explicit `name` → `RECEIPT_VLM_MODEL` env → `DEFAULT_VLM_MODEL` (`moondream-0.5b`).

### 7.3 `VlmProvider` interface (`backends/vlm/base.py`)

```python
class VlmProvider(ABC):
    @property
    def model_id(self) -> str: ...

    @abstractmethod
    def analyze(self, image_path: str, prompt: str) -> str: ...
```

`GroqProvider` and `MoondreamProvider` also implement:

```python
def analyze_with_options(
    self, image_path: str, prompt: str, *, crop_mode: str | None = None
) -> str: ...
```

`MoondreamProvider` may implement `analyze_queries` for multipass batching.

### 7.4 VLM modes (`VlmMode` enum)

| Mode | Value | Groq | Moondream | Output from `extract_text` |
|------|-------|------|-----------|---------------------------|
| Transcribe | `transcribe` | **Rejected at init** | Yes | Cleaned plain text → heuristic parser |
| JSON | `json` | **Required** | Yes | JSON string → `try_parse_vlm_json` |
| Multipass | `multipass` | **Rejected at init** | Yes | Merged JSON from 3 focused prompts |

Env: `RECEIPT_VLM_MODE` (default `transcribe` globally, but Groq forces `json`).

### 7.5 Extraction orchestration (`backends/vlm/extraction.py`)

```python
def run_vlm_extraction(provider: VlmProvider, image_path: str) -> str
```

- Builds retry attempts: `max(1, RECEIPT_VLM_MAX_RETRIES + 1)` (default 3 attempts)
- **json mode:** `RECEIPT_EXTRACTION_PROMPT` then `RECEIPT_EXTRACTION_STRICT_PROMPT`; second attempt may use `crop_mode=center`
- **transcribe mode:** transcription prompts + `clean_vlm_transcription`
- **multipass:** `run_multipass_extraction` (header/date/products) — not for Groq
- Each attempt: `validate_vlm_output(mode, output)` — on failure, retry; else `ReceiptParseError` with snippet

### 7.6 Prompts (`backends/vlm/prompts.py`)

French prompts instruct the model to return **only JSON** matching the canonical schema (for json mode). Key constants:

- `RECEIPT_EXTRACTION_PROMPT` — full schema + rules
- `RECEIPT_EXTRACTION_STRICT_PROMPT` — minimal template for retry
- `RECEIPT_TRANSCRIPTION_*` — plain text (Moondream only)
- `MULTIPASS_*` — partial JSON (Moondream only)

**Refactoring:** Prompt changes are the lowest-risk lever for extraction quality on Groq without touching parser heuristics.

### 7.7 JSON parsing (`vlm_parse.py`)

Key functions:

| Function | Purpose |
|----------|---------|
| `try_parse_vlm_json(text)` | Entry used by `ReceiptParser`; returns `dict` or `None` |
| `normalize_vlm_ticket(payload)` | Validates/coerces types; dedupes products; date coercion |
| `loads_vlm_payload(text)` | Raw dict parse with `json_repair` fallback |
| `merge_partial_tickets(parts)` | Multipass merge helper |

Behaviors relevant to refactoring:

- Strips markdown ```json fences
- Handles duplicated JSON blobs in one response (scores candidates by product count)
- Optional dependency `json-repair` for malformed JSON
- Product dedup key: `(nom_produit, prix_unitaire_ou_kg, unites)`
- Rejects chain names that look like model chatter (`vlm_validate.looks_like_store_name`)
- Date coercion from `DD/MM/YYYY HH:MM` variants to `yyyyMMdd HH:mm`

### 7.8 Validation (`vlm_validate.py`)

```python
def validate_vlm_output(mode: str, text: str) -> VlmValidationResult
```

**json mode checks:**

- `try_parse_vlm_json` succeeds
- Not empty ticket (chain or products required)
- `chaine_supermarche` passes `looks_like_store_name` if non-empty

Failed validation triggers retry with stricter prompt / center crop.

### 7.9 Image preparation (`vlm_image_prep.py`)

```python
@dataclass(frozen=True)
class VlmImageConfig:
    max_image_side: int = 1536
    crop_mode: str = "auto"      # auto | center | off
    crop_margin: float = 0.05
    jpeg_quality: int = 95

def prepare_vlm_image(path, config, *, crop_mode_override=None) -> tuple[str, list[Path]]
```

- **auto crop:** contrast-based receipt bounding box (Pillow only)
- **center crop:** 70% center region (retry strategy)
- Writes JPEG temp files; caller must `cleanup_temp_files`
- Used by both Groq and Moondream

Groq adds a **post-prep size check:** raw file bytes must be ≤ `GROQ_BASE64_MAX_BYTES` (3_500_000) before base64 encoding.

---

## 8. `GroqProvider` — implementation reference

**File:** `src/receipt_ocr/backends/vlm/groq_provider.py`

### 8.1 Construction constraints

```python
class GroqProvider(VlmProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        image_config: VlmImageConfig | None = None,
    ) -> None:
```

- Calls `_require_json_vlm_mode()` — raises `OcrBackendError` if `RECEIPT_VLM_MODE != "json"`
- `model_id` property always returns `"groq-llama4-scout"` (registry id, not API model name)
- API model id: `RECEIPT_GROQ_MODEL` or default `meta-llama/llama-4-scout-17b-16e-instruct`

### 8.2 API call shape

Uses official `groq` Python SDK:

```python
client.chat.completions.create(
    model=self._groq_model,
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},  # data:image/jpeg;base64,...
        ],
    }],
    temperature=self._temperature,       # RECEIPT_VLM_TEMPERATURE, default 0.1
    max_completion_tokens=self._max_tokens,  # RECEIPT_VLM_MAX_TOKENS, default 4096 for Groq
    response_format={"type": "json_object"},
)
```

### 8.3 API key resolution

```python
def resolve_groq_api_key() -> str
```

Reads `GROQ_API_KEY` then legacy `groq_key` from environment (typically `.env` via `load_project_env()`).

### 8.4 Dependencies

`requirements-groq.txt`:

```
groq>=0.13.0
python-dotenv>=1.0.0
Pillow>=10.0.0
json-repair>=0.30.0
```

Package is **not** in base `requirements.txt` — install explicitly for Groq work.

### 8.5 What NOT to change without explicit need

| Constraint | Reason |
|------------|--------|
| Keep `BackendName.VLM` — no separate `BackendName.GROQ` | Swappable providers under one backend |
| Groq must stay json-only | Cloud JSON mode + parser short-circuit |
| Preserve `extract_receipt` signature | Downstream worker contract alignment |
| Preserve output schema keys | `TicketField` / `ProductField` enums used in tests |

---

## 9. Environment variables (complete reference)

### 9.1 Backend selection

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECEIPT_OCR_BACKEND` | `paddle` | `paddle` \| `ppocrv4` \| `tesseract` \| `easyocr` \| **`vlm`** |
| `RECEIPT_VLM_MODEL` | `moondream-0.5b` | **`groq-llama4-scout`** for Groq |
| `RECEIPT_VLM_MODE` | `transcribe` | Must be **`json`** for Groq |

### 9.2 Groq-specific

| Variable | Default | Purpose |
|----------|---------|---------|
| `GROQ_API_KEY` | — | Primary API key |
| `groq_key` | — | Legacy alias (still supported) |
| `RECEIPT_GROQ_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq API model id |

### 9.3 Shared VLM tuning

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1536` | Resize longest edge (`0` = off) |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | Extra attempts after first failure |
| `RECEIPT_VLM_CROP` | `auto` | `auto` \| `center` \| `off` |
| `RECEIPT_VLM_CROP_MARGIN` | `0.05` | Padding for auto crop |
| `RECEIPT_VLM_JPEG_QUALITY` | `95` | Temp JPEG quality |
| `RECEIPT_VLM_TEMPERATURE` | `0.1` | Generation temperature |
| `RECEIPT_VLM_MAX_TOKENS` | `1024` (Moondream) / **4096 default in GroqProvider** | Max completion tokens |

### 9.4 Classical OCR (not used for Groq path)

| Variable | Default | Backend |
|----------|---------|---------|
| `RECEIPT_OCR_MAX_IMAGE_SIDE` | `1280` | paddle |
| `RECEIPT_OCR_CPU_THREADS` | `2` | paddle |
| `RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE` | `640` | ppocrv4 |

---

## 10. Testing

### 10.1 Markers (`pyproject.toml`)

- `integration` — real images under `data/raw/`
- `groq` — live Groq API (skipped without API key or with `--no-integration`)

### 10.2 Key test files

| File | What it verifies |
|------|------------------|
| `tests/test_extract_receipt.py` | Public API, backend swap, env selection, caching |
| `tests/test_parser.py` | Heuristic parser on fixture OCR strings |
| `tests/test_parser_vlm_json.py` | VLM JSON normalization edge cases |
| `tests/test_groq_provider.py` | Groq rejects transcribe/multipass (no HTTP) |
| `tests/test_groq_integration.py` | Live Groq + schema assertions on real images |
| `tests/test_vlm_validate.py` | Validation heuristics |
| `tests/test_vlm_extraction.py` | Retry / attempt building |

### 10.3 Commands

```bash
cd dev_ocr
pytest --no-integration                    # Fast unit tests
pytest -m groq                           # Live Groq (needs API key + images)
pytest -m integration                      # Paddle on real images
```

`conftest.py` auto-skips integration when `data/raw/` has no images; skips `groq` when no API key.

---

## 11. Scripts (operational)

| Script | Purpose |
|--------|---------|
| `scripts/test_groq_receipt.py` | One image → `extract_receipt` with Groq env |
| `scripts/test_extract_receipt.py` | Generic pipeline test + schema validation |
| `scripts/run_vlm_test.py` | Moondream local tests |
| `scripts/benchmark_vlm.py` | Compare VLM modes |
| `scripts/smoke_test_ocr.py` | Classical OCR smoke test |
| `scripts/download_datasets.py` | HuggingFace/Kaggle receipt datasets |

---

## 12. Refactoring guide for LLM implementers

When the architecture document asks to adapt this codebase (e.g. wrap in a Cloud Run worker, add batching, change schema mapping, add observability), use this checklist:

### 12.1 Safe extension points

1. **New VLM provider:** Implement `VlmProvider`, register in `registry.py`, add `VlmModelName` enum value.
2. **Groq prompt/schema tuning:** Edit `prompts.py`; adjust `normalize_vlm_ticket` if new fields are required in output.
3. **Retry/validation policy:** `extraction.py`, `vlm_validate.py`.
4. **Image prep:** `vlm_image_prep.py` (affects Groq payload size).
5. **Inject backend explicitly:** `extract_receipt(path, backend=VlmBackend(provider=...))` — no factory cache issues.
6. **Post-process canonical dict:** Prefer wrapping `extract_receipt` in caller rather than changing schema inside package (unless spec explicitly requires schema change).

### 12.2 High-risk change areas

- **`parser.py` heuristics** — large, intertwined regex/state machine; only needed for non-JSON backends.
- **`extract_receipt` return schema** — breaks `test_groq_integration`, `project_guidelines.md`, worker mapping.
- **Removing json short-circuit in `parse_text`** — would force Groq JSON through OCR heuristics (wrong).
- **Making Groq support transcribe/multipass** — explicitly rejected; would need new validation paths.

### 12.3 Typical integration pattern (worker / service)

The production worker (`workers/ocr/`) will likely:

1. Download image bytes from GCS
2. Write temp file or pass bytes to a thin adapter
3. Set env: `RECEIPT_OCR_BACKEND=vlm`, `RECEIPT_VLM_MODEL=groq-llama4-scout`, `RECEIPT_VLM_MODE=json`, secrets for `GROQ_API_KEY`
4. Call `extract_receipt(temp_path)` 
5. Map `dict["ticket"]` → SQL rows (`enseigne`, `ticket_date`, `prix_extraits.raw_text`, `unit_price`, `quantity`, …) per `workers/ocr/ocr-worker-contract.md`

**Schema mapping note:** SQL contract uses `raw_text`, `unit_price`, `quantity`, `line_total` per line — not identical to `nom_produit` / `prix_unitaire_ou_kg` / `unites`. A mapper layer in the worker is expected.

### 12.4 Packaging / deployment considerations

- Current package is **not** vendored into `workers/ocr/` yet — expect either:
  - Copy/submodule `src/receipt_ocr` into worker package, or
  - Publish/install as dependency
- Groq path avoids heavy local models (no Moondream weights, no Paddle) — suitable for lean Cloud Run images **if** `requirements-groq.txt` deps are included and network egress to Groq is allowed.
- Cold start: `GroqProvider` lazy-inits SDK client on first request; no model download.
- **Secrets:** Use Secret Manager for `GROQ_API_KEY` in prod; `load_project_env()` is for local dev only.

---

## 13. Related repository documents

| Path | Content |
|------|---------|
| `dev_ocr/project_guidelines.md` | Original spec (schema, architecture rules) |
| `dev_ocr/README.md` | Human setup, env tables, test commands |
| `dev_ocr/documentation/entries/2026-05-25-groq-vlm-provider.md` | Changelog entry for Groq implementation |
| `workers/ocr/ocr-worker-contract.md` | Production HTTP/Pub/Sub/SQL contract (target consumer) |
| `workers/ocr/prompt_for_ocr_worker_development.md` | Meta-prompt for worker development |

---

## 14. Quick reference — files to edit by task type

| Task | Primary files |
|------|----------------|
| Change public API | `extract_receipt.py`, `__init__.py` |
| Change output schema | `constants.py`, `vlm_parse.py`, `parser.py`, `prompts.py`, tests |
| Groq API behavior | `groq_provider.py`, `constants.py` |
| Swap/configure VLM model | `registry.py`, env vars |
| Improve JSON quality | `prompts.py`, `vlm_validate.py`, `vlm_parse.py` |
| Image size / crop issues | `vlm_image_prep.py`, `GROQ_BASE64_MAX_BYTES` in `constants.py` |
| Add retry logic | `extraction.py` |
| Worker integration | New code under `workers/ocr/` consuming `extract_receipt` |

---

## 15. Type and control-flow summary (for codegen)

```python
# Types (conceptual — not exported as TypedDict today)
ReceiptDict = dict  # {"ticket": {"date": str, "chaine_supermarche": str, "adresse": str, "produits": list[ProductDict]}}
ProductDict = dict  # {"nom_produit": str, "prix_unitaire_ou_kg": float, "unites": int}

# Control flow for Groq
def extract_receipt(image_path: str, backend: OcrBackend | None = None) -> ReceiptDict:
    backend = backend or build_backend()  # VlmBackend when RECEIPT_OCR_BACKEND=vlm
    return ReceiptParser(backend).parse(image_path)

# Inside VlmBackend.extract_text → str (JSON)
# Inside ReceiptParser.parse_text → ReceiptDict via try_parse_vlm_json
```

This document is intentionally **self-contained**: an LLM with this file plus the target architecture spec should be able to plan refactors and generate implementation prompts without re-reading the repository tree.
