# worker-ocr-paddle

Worker OCR, backend **PaddleOCR** (français, CPU).

Un des 5 workers « un backend = un worker » issus de `dev_ocr`. Le pipeline
commun vit dans [`libs/pricetracker_receipt_pipeline`](../../libs/pricetracker_receipt_pipeline) ;
seul `paddle_backend.py` est propre à ce worker.

## Flux

`Pub/Sub push (topic ocr-paddle)` → `POST /push` (OIDC) → `tickets.gcs_path` →
image GCS → `PaddleOcrBackend` (texte brut) → `ReceiptParser` (heuristiques
tickets français) → `alias_lookup` (EAN) → écriture atomique `prix_extraits` +
`tickets`.

Réponses : `204` = ACK (succès **ou** échec déterministe), `400` = payload
malformé (ACK), `5xx` = erreur transitoire → NACK → retry → DLQ après 5 essais.

## Modèles

Les modèles de détection/reconnaissance Paddle sont **baked dans l'image** au
build (téléchargés depuis le CDN Paddle, cf. `Dockerfile`) : pas de
téléchargement ni d'accès réseau au cold start.

## Variables d'environnement

| Var | Défaut | Rôle |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | Projet GCP. |
| `PRT_OCR_ENGINE_LABEL` | `paddleocr` | Écrit dans `tickets.ocr_engine` / `ocr_model`. |
| `RECEIPT_OCR_MAX_IMAGE_SIDE` | `1280` | Redimensionnement avant OCR (`0` = désactivé). |
| `RECEIPT_OCR_CPU_THREADS` | `2` | Plafond threads BLAS/OpenMP. |
| `PRT_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` / `POOL_SIZE` | — / 5432 / `price_tracker` / `pt_app` / — / 4 | Cloud SQL. `PASSWORD` = secret `prt-prod-cloudsql-password`. |
| `PRT_OIDC_DISABLE` | `0` | `1` = bypass OIDC (dev local uniquement). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | — | Allowlist des appelants. |
| `PRT_LOG_LEVEL` | `INFO` | Niveau des logs structlog. |

## Développement

```bash
uv sync          # installe paddlepaddle (~100 Mo)
uv run pytest    # le backend est monkeypatché : Paddle n'est jamais chargé
```

## Build

Depuis la **racine du monorepo** :

```bash
docker build -f workers/ocr-paddle/Dockerfile -t worker-ocr-paddle:dev .
gcloud builds submit . --config=workers/ocr-paddle/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD) \
  --project=price-tracker-prod-01
```

Déploiement : bumper `worker_ocr_paddle_image_tag` dans
`infra/envs/prod/variables.tf`, puis `terraform apply`.
