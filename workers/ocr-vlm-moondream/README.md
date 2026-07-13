# worker-ocr-vlm-moondream

Worker OCR, backend **VLM Moondream 0.5B (int8, inférence locale CPU)**.

Un des 4 workers « un backend = un worker » issus de `dev_ocr`. Le pipeline
commun vit dans [`libs/pricetracker_receipt_pipeline`](../../libs/pricetracker_receipt_pipeline) ;
seul `moondream_provider.py` est propre à ce worker.

## Flux

`Pub/Sub push (topic ocr-vlm-moondream)` → `POST /push` (OIDC) →
`tickets.gcs_path` → image GCS → `MoondreamProvider` (poids `.mf` locaux) →
`ReceiptParser` → `alias_lookup` (EAN) → écriture atomique.

Contrat HTTP commun aux workers OCR : `204` acquitte (succès comme échec
déterministe), `400` sur payload malformé, `5xx` seulement sur panne transitoire,
qui part alors en retry puis en DLQ.

## Poids modèle

Ils ne sont **pas** dans l'image. Au démarrage (`lifespan`), le worker télécharge
`PRT_MODEL_GCS_URI` vers `PRT_MODEL_LOCAL_DIR` (idempotent) et pose
`RECEIPT_VLM_MODEL_PATH`. Un échec fait échouer le démarrage : Cloud Run relance
et aucun message n'est ACKé par un worker sans poids.

Prérequis ops (une fois) :

```bash
gsutil cp dev_ocr/data/models/moondream-0_5b-int8.mf \
  gs://price-tracker-prod-01-models/vlm/moondream/v1/
```

## Variables d'environnement

| Var | Défaut | Rôle |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | Projet GCP. |
| `PRT_OCR_ENGINE_LABEL` | `moondream-0.5b` | Écrit dans `tickets.ocr_engine` / `ocr_model`. |
| `PRT_MODEL_GCS_URI` | — | URI `gs://` du `.mf`. Vide = pas de bootstrap (dev local avec `RECEIPT_VLM_MODEL_PATH` déjà posé). |
| `PRT_MODEL_LOCAL_DIR` | `/tmp/models` | Destination du download. |
| `RECEIPT_VLM_MODE` | `transcribe` | `transcribe` \| `json` \| `multipass`. |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | Tentatives (prompt strict + crop centré à l'escalade). |
| `PRT_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` / `POOL_SIZE` | — / 5432 / `price_tracker` / `pt_app` / — / 4 | Cloud SQL. `PASSWORD` = secret `prt-prod-cloudsql-password`. |
| `PRT_OIDC_DISABLE` | `0` | `1` = bypass OIDC (dev local uniquement). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | — | Allowlist des appelants. |
| `PRT_LOG_LEVEL` | `INFO` | Niveau des logs structlog. |

## Développement

```bash
uv sync
uv run pytest
```

## Build

Depuis la **racine du monorepo** :

```bash
docker build -f workers/ocr-vlm-moondream/Dockerfile -t worker-ocr-vlm-moondream:dev .
gcloud builds submit . --config=workers/ocr-vlm-moondream/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD) \
  --project=price-tracker-prod-01
```

Déploiement : bumper `worker_ocr_vlm_moondream_image_tag` dans
`infra/envs/prod/variables.tf`, puis `terraform apply`.
