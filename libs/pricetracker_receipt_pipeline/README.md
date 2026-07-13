# pricetracker-receipt-pipeline

Code commun des workers OCR « un worker par backend » : `workers/ocr-paddle`,
`ocr-vlm-moondream`, `ocr-vlm-receipt`, `ocr-vlm-scratch`.

`dev_ocr/` reste la source de recherche. Cette lib en est une copie figée, adaptée
au déploiement : un correctif de parsing doit donc être porté ici pour atteindre la
prod, ce qui est le prix à payer pour que `dev_ocr` puisse bouger sans redéployer
quoi que ce soit.

## Deux couches

### 1. Pipeline (racine du paquet) — copié de `dev_ocr/src/receipt_ocr`

| Module | Rôle |
|---|---|
| `parser.py` | `ReceiptParser` — texte OCR → dict canonique. Court-circuite sur JSON VLM valide. |
| `constants.py` | Schéma de sortie, enums, noms des env vars `RECEIPT_*`. |
| `exceptions.py` | `ReceiptOcrError` → `OcrBackendError`, `ReceiptParseError`. |
| `vlm_parse.py` / `vlm_validate.py` / `vlm_image_prep.py` / `vlm_text_cleanup.py` | Helpers VLM (parsing JSON, validation → retry, crop+resize, nettoyage). |
| `env.py` | Lecture typée des env vars (pas de chargement de `.env` : la config vient de Cloud Run). |
| `backends/base.py` | ABC `OcrBackend` : `extract_text(image_path) -> str`. |
| `backends/vlm_backend.py` | `VlmBackend(provider)` — provider **obligatoire** (pas de registre). |
| `backends/vlm/` | ABC `VlmProvider`, `run_vlm_extraction` (modes + retries), multipass, prompts. |

Non copié depuis `dev_ocr` : `extract_receipt.py` et `backends/vlm/registry.py`
(des factories, inutiles quand le worker câble un seul backend en dur), les stubs
tesseract/easyocr, et les backends concrets. Ces derniers vivent dans le worker qui
les utilise, pour que `paddlepaddle` ne parte pas dans l'image Moondream ni `torch`
dans l'image Paddle.

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
