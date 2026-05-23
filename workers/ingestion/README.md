# worker-ingestion

Worker Cloud Run de la **Phase 6.1**. Cron quotidien 03h UTC, invoqué par
`prt-prod-trigger-ingestion` (Cloud Scheduler, OIDC).

## Pipeline

1. Téléchargement du snapshot Parquet `openfoodfacts/open-prices` depuis le
   Hub HuggingFace (token `prt-prod-hf-token`).
2. Filtre `country_code = 'FR'`, dédup sur `id`, normalisation `kind` et
   `date`.
3. Upload `snapshot.parquet` dans `gs://price-tracker-prod-01-bronze/open-prices/dt=YYYY-MM-DD/`
   (versioning bucket = ON, donc on garde l'historique sans rotation custom).
4. Load BigQuery en table temporaire `_stg_open_prices_<run_id>` puis
   `MERGE` sur `id` vers `prt_prod_silver.open_prices_clean`. Re-runs sûrs.

## Endpoints

| Méthode | Path | Caller | Réponse |
|---|---|---|---|
| `POST` | `/run` | Cloud Scheduler (OIDC `prt-prod-worker-sa`) | `{snapshot_date, rows_inserted, duration_s}` |
| `GET`  | `/healthz` | Cloud Run probes / debug humain | `{status: "ok"}` |

## Configuration (env vars)

Pas de hardcoding — tout vient de l'environnement ou des secrets injectés
par Cloud Run.

| Var | Source | Défaut | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ADC / Cloud Run | — | project_id GCP, lu via `ADC.project_id`. |
| `PRT_GCP_REGION` | env Cloud Run | `europe-west1` | Région pour BigQuery jobs. |
| `PRT_BRONZE_BUCKET` | env Cloud Run | `price-tracker-prod-01-bronze` | Bucket d'archivage du snapshot. |
| `PRT_BQ_DATASET_SILVER` | env Cloud Run | `prt_prod_silver` | Dataset cible. |
| `PRT_BQ_TABLE_OPEN_PRICES` | env Cloud Run | `open_prices_clean` | Table cible (MERGE). |
| `PRT_HF_DATASET` | env Cloud Run | `openfoodfacts/open-prices` | Dataset HuggingFace. |
| `PRT_HF_FILENAME` | env Cloud Run | `prices.parquet` | Fichier du snapshot. |
| `PRT_FILTER_COUNTRY_CODE` | env Cloud Run | `FR` | Filtre géo (vide = pas de filtre). |
| `PRT_OIDC_REQUIRED_AUDIENCE` | env Cloud Run | URL service | Audience attendue dans le JWT OIDC. |
| `PRT_OIDC_ALLOWED_ISSUERS` | env Cloud Run | `https://accounts.google.com` | Issuer Google (CSV). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | env Cloud Run | `prt-prod-worker-sa@…` | SA autorisé(s) en CSV. |
| `HF_TOKEN` | **secret** `prt-prod-hf-token` | — | Token lecture HuggingFace. |

## Développement local

```bash
cd workers/ingestion
uv sync
uv run pytest

# Smoke run local (nécessite gcloud auth ADC + HF_TOKEN exporté)
gcloud auth application-default login
export HF_TOKEN=$(gcloud secrets versions access latest --secret=prt-prod-hf-token --project=price-tracker-prod-01)
export GOOGLE_CLOUD_PROJECT=price-tracker-prod-01
# Le check OIDC peut être désactivé en dev :
export PRT_OIDC_DISABLE=1
uv run uvicorn pricetracker_ingestion.main:app --reload --port 8080
curl -X POST http://localhost:8080/run
```

## Build & deploy

Voir `docs/phase-06-handoff.md` §"Déploiement après codage".
