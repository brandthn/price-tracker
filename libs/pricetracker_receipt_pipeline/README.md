# pricetracker-receipt-pipeline

Code commun des workers OCR « un worker par backend » (`workers/ocr-paddle`,
`ocr-ppocrv4`, `ocr-vlm-moondream`, `ocr-vlm-groq`, `ocr-vlm-receipt`,
`ocr-vlm-scratch`).

`dev_ocr/` reste la source de recherche, non modifiée. Cette lib en est une
copie figée, adaptée au déploiement.

## Deux couches

### 1. Pipeline (racine du paquet) — copié de `dev_ocr/src/receipt_ocr`

| Module | Rôle |
|---|---|
| `parser.py` | `ReceiptParser` — texte OCR → dict canonique. Court-circuite sur JSON VLM valide. |
| `constants.py` | Schéma de sortie, enums, noms des env vars `RECEIPT_*`. |
| `exceptions.py` | `ReceiptOcrError` → `OcrBackendError`, `ReceiptParseError`. |
| `vlm_parse.py` / `vlm_validate.py` / `vlm_image_prep.py` / `vlm_text_cleanup.py` | Helpers VLM (parsing JSON, validation → retry, crop+resize, nettoyage). |
| `image_utils.py` | Redimensionnement pour les backends OCR classiques. |
| `backends/base.py` | ABC `OcrBackend` : `extract_text(image_path) -> str`. |
| `backends/vlm_backend.py` | `VlmBackend(provider)` — provider **obligatoire** (pas de registre). |
| `backends/vlm/` | ABC `VlmProvider`, `run_vlm_extraction` (modes + retries), multipass, prompts. |

Non copié depuis `dev_ocr` : `extract_receipt.py` et `backends/vlm/registry.py`
(factories — chaque worker câble un seul backend en dur), `env.py` (remplacé par
pydantic-settings), les stubs tesseract/easyocr, et les backends concrets (ils
vivent dans le worker qui les utilise).

### 2. Runtime worker (`worker/`) — calqué sur `workers/ocr-llm`

| Module | Rôle |
|---|---|
| `config.py` | `BaseWorkerSettings` — env vars `PRT_*`. Chaque worker hérite et expose son `get_settings()` `@lru_cache`. |
| `auth.py` | `build_verify_oidc(get_settings)` → dépendance FastAPI de vérif OIDC. |
| `logging.py` | structlog → JSON stdout (champ `severity` pour Cloud Logging). |
| `gcs.py` | `split_gs_uri`, `download_image`, `ImageTooLargeError`. |
| `pubsub.py` | `parse_push_envelope(body) -> ticket_id`. |
| `pg.py` | `create_pool`, `get_ticket`, `persist_result` (DELETE → INSERT → bump `ocr_attempts`, en une transaction). |
| `mapper.py` | dict canonique → rows `tickets` / `prix_extraits`. |
| `weights.py` | `ensure_weights(gs_uri, dest_dir)` — download GCS idempotent au démarrage. |

## Développement

```bash
cd libs/pricetracker_receipt_pipeline
uv sync
uv run pytest
```

Les workers la consomment par chemin local (jamais d'index PyPI) :

```toml
[tool.uv.sources]
pricetracker-receipt-pipeline = { path = "../../libs/pricetracker_receipt_pipeline" }
```

et leur Dockerfile la copie dans le contexte de build (racine du monorepo) :
`COPY libs/pricetracker_receipt_pipeline /app/libs/pricetracker_receipt_pipeline`.
