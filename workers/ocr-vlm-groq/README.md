# worker-ocr-vlm-groq

Worker OCR, backend **VLM Groq — `meta-llama/llama-4-scout-17b-16e-instruct`**.

Un des 6 workers « un backend = un worker » issus de `dev_ocr`. Le pipeline
commun (parser, orchestration VLM, runtime Pub/Sub + Cloud SQL) vit dans
[`libs/pricetracker_receipt_pipeline`](../../libs/pricetracker_receipt_pipeline) ;
seul `groq_provider.py` est propre à ce worker.

## Flux

`Pub/Sub push (topic ocr-vlm-groq)` → `POST /push` (OIDC) → `tickets.gcs_path`
→ image GCS → `GroqProvider` (API cloud, JSON mode) → `ReceiptParser`
→ `pricetracker_matching.alias_lookup` (EAN) → écriture atomique
`prix_extraits` + `tickets`.

Réponses : `204` = ACK (succès **ou** échec déterministe), `400` = payload
malformé (ACK), `5xx` = erreur transitoire → NACK → retry → DLQ après 5 essais.

## Endpoints

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/healthz` | Liveness Cloud Run. Répond seulement après le `lifespan` (backend construit + pool PG prêt). |
| `POST` | `/push` | Enveloppe Pub/Sub push `{"ticket_id": "..."}`, protégée par OIDC. |

## Variables d'environnement

| Var | Défaut | Rôle |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | Projet GCP. |
| `PRT_OCR_ENGINE_LABEL` | `groq-llama4-scout` | Écrit dans `tickets.ocr_engine` / `ocr_model`. |
| `RECEIPT_VLM_MODE` | `transcribe` (lib) → **doit être `json`** | `GroqProvider` refuse tout autre mode au démarrage. |
| `RECEIPT_GROQ_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Override du modèle Groq. |
| `GROQ_API_KEY` | — | **Secret** (`prt-prod-groq-api-key`). |
| `PRT_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` / `POOL_SIZE` | — / 5432 / `price_tracker` / `pt_app` / — / 4 | Cloud SQL. `PASSWORD` = secret `prt-prod-cloudsql-password`. |
| `PRT_OIDC_DISABLE` | `0` | `1` = bypass OIDC (dev local uniquement). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | — | Allowlist des appelants. |
| `PRT_LOG_LEVEL` | `INFO` | |

## Développement

```bash
uv sync
uv run pytest
```

## Build

Depuis la **racine du monorepo** (le contexte doit contenir `libs/`) :

```bash
docker build -f workers/ocr-vlm-groq/Dockerfile -t worker-ocr-vlm-groq:dev .
gcloud builds submit . --config=workers/ocr-vlm-groq/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD) \
  --project=price-tracker-prod-01
```

Déploiement : bumper `worker_ocr_vlm_groq_image_tag` dans
`infra/envs/prod/variables_ocr_backends.tf`, puis `terraform apply`.
