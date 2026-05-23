# worker-off

Worker Cloud Run de la **Phase 6.2**. Cron quotidien 04h UTC, invoqué par
`prt-prod-trigger-off` (Cloud Scheduler, OIDC).

## Pipeline

1. **Discovery** : lit dans `prt_prod_silver.open_prices_clean` la liste des
   EAN distincts présents mais absents de `prt_prod_silver.catalogue_produits`
   (`LEFT JOIN ... WHERE c.ean IS NULL`), borne à `PRT_OFF_MAX_EANS_PER_RUN`.
2. **OFF API** : pour chaque EAN, `GET /api/v2/product/<ean>?fields=...`
   en respectant **15 req/min/IP** (politique officielle OFF). Backoff
   exponentiel sur 429 / 5xx via `tenacity`.
3. **Embeddings Vertex** : pour les EAN enrichis avec succès, on batche
   les textes (`name + brand + category_l3`) par groupes de 250 et on appelle
   `text-embedding-004` (dim 768).
4. **Écriture double** :
   - BQ Silver `catalogue_produits` via MERGE sur `ean` (load staging puis MERGE).
   - Cloud SQL `products` (table pgvector) via `INSERT ... ON CONFLICT (ean) DO UPDATE`.

Les EAN absents de OFF (404) sont **quand même écrits** avec `off_found=false`
pour ne pas être re-tentés à chaque run (tombstone).

## Endpoints

| Méthode | Path | Caller | Réponse |
|---|---|---|---|
| `POST` | `/run` | Cloud Scheduler (OIDC `prt-prod-worker-sa`) | `{enqueued, off_found, off_not_found, embedded, rows_upserted, duration_s}` |
| `GET`  | `/healthz` | Cloud Run probes / debug humain | `{status: "ok"}` |

## Rate limit OFF — pourquoi 15 req/min ?

Doc officielle OFF (https://openfoodfacts.github.io/openfoodfacts-server/api/#rate-limits) :
- **15 req/min/IP** pour `GET /api/v*/product` (notre cas)
- **10 req/min/IP** pour les endpoints de recherche

Le handoff initial proposait 100 req/min, **incorrect** par rapport à la
politique 2026 de OFF. Restant à 15 req/min on évite tout risque de ban IP.
Cap effectif par run : ~800 EAN sur 60 min (timeout Cloud Run gen2 max).
Le cron quotidien rattrape le reste — `MERGE` garantit l'idempotence.

## Configuration (env vars)

| Var | Source | Défaut | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ADC / Cloud Run | — | project_id GCP. |
| `PRT_GCP_REGION` | env Cloud Run | `europe-west1` | Région BQ + Vertex. |
| `PRT_BQ_DATASET_SILVER` | env Cloud Run | `prt_prod_silver` | Dataset cible. |
| `PRT_BQ_TABLE_OPEN_PRICES` | env Cloud Run | `open_prices_clean` | Source EAN. |
| `PRT_BQ_TABLE_CATALOGUE` | env Cloud Run | `catalogue_produits` | Table catalogue (MERGE). |
| `PRT_OFF_BASE_URL` | env Cloud Run | `https://world.openfoodfacts.org` | Endpoint OFF. |
| `PRT_OFF_USER_AGENT` | env Cloud Run | `pricetracker-prt-prod/0.1 (+https://github.com/.../price-tracker)` | UA conformeOFF. |
| `PRT_OFF_RATE_RPM` | env Cloud Run | `15` | Rate limit en req/min, conforme OFF. |
| `PRT_OFF_MAX_EANS_PER_RUN` | env Cloud Run | `2000` | Cap dur (validé utilisateur). |
| `PRT_OFF_RUN_TIMEOUT_S` | env Cloud Run | `3500` | Stop le worker avant le timeout Cloud Run (3600s gen2). |
| `PRT_VERTEX_MODEL` | env Cloud Run | `text-embedding-004` | Modèle d'embedding. |
| `PRT_VERTEX_BATCH` | env Cloud Run | `250` | Taille de batch Vertex (max 250). |
| `PRT_PG_HOST` | env Cloud Run | private IP de `prt-prod-sql-main` | Cloud SQL via Direct VPC egress. |
| `PRT_PG_PORT` | env Cloud Run | `5432` | — |
| `PRT_PG_DB` | env Cloud Run | `price_tracker` | — |
| `PRT_PG_USER` | env Cloud Run | `pt_app` | — |
| `PRT_PG_PASSWORD` | **secret** `prt-prod-cloudsql-password` | — | Password DB. |
| `PRT_OIDC_*` | env Cloud Run | cf. worker-ingestion | Même grille de vérification OIDC. |

## Développement local

```bash
cd workers/off
uv sync
uv run pytest

# Smoke run local — nécessite Cloud SQL Auth Proxy actif sur 127.0.0.1:5432 +
# ADC GCP + désactivation OIDC.
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=price-tracker-prod-01
export PRT_OIDC_DISABLE=1
export PRT_PG_HOST=127.0.0.1
export PRT_PG_PASSWORD=$(gcloud secrets versions access latest --secret=prt-prod-cloudsql-password --project=price-tracker-prod-01)
# Démarrer le proxy en parallèle :
# ./cloud-sql-proxy --private-ip price-tracker-prod-01:europe-west1:prt-prod-sql-main &
uv run uvicorn pricetracker_off.main:app --reload --port 8080
curl -X POST http://localhost:8080/run
```

## Build & deploy

Voir `docs/phase-06-handoff.md` §"Déploiement après codage".
