# backend — PriceTracker FastAPI

API REST scale-to-zero sur Cloud Run (Phase 7). Vérifie les JWT Firebase via
ADC (sans clé JSON), génère des Signed URLs V4 pour l'upload de tickets, lit
BigQuery (catalogue + observatoire) et Cloud SQL Postgres+pgvector
(users/tickets/products).

## Endpoints

| Méthode | Path | Auth | Fait quoi |
|---|---|---|---|
| GET | `/healthz` | non | Liveness probe Cloud Run. |
| POST | `/tickets/upload-url` | oui | Génère Signed URL V4 PUT 15min + crée ticket `pending`. |
| GET | `/tickets` | oui | Liste paginated tickets de l'utilisateur. |
| GET | `/tickets/{id}` | oui | Ticket + lignes `prix_extraits`. |
| PATCH | `/tickets/{id}/items` | oui | Validation/correction items OCR. |
| GET | `/indices/personal` | oui | Indice perso (BQ Gold + `user_basket_history`). |
| GET | `/indices/national` | non | Indice national (BQ Gold). |
| GET | `/indices/regional/{dept}` | non | Indice par département (BQ Gold). |
| GET | `/observatoire/rankings` | non | Top hausses du mois. |
| GET | `/observatoire/hall-of-shame` | non | Produits en hausse les plus achetés. |
| GET | `/observatoire/map` | non | Choroplèthe FR par département. |
| GET | `/products/{ean}` | non | Détail produit (`catalogue_produits` BQ). |
| GET | `/products/search?q=` | non | Recherche full-text BQ. |
| GET | `/products/{ean}/substitutes` | non | Top-K substituts via pgvector. |
| GET | `/stats/brand/{brand}` | non | Stats par marque (top hausses, prix moyen). |
| GET | `/me` | oui | Profil utilisateur. |
| PATCH | `/me` | oui | Mise à jour profil. |
| PATCH | `/me/preferences` | oui | Seuils alertes, enseignes préférées. |

OpenAPI/Swagger disponible sur `/docs` (activé en prod via `PRT_OPENAPI_ENABLED=true`).

## Auth Firebase (sans clé JSON)

Org policy `iam.disableServiceAccountKeyCreation` interdit la création de
clés JSON. `firebase_admin.initialize_app()` est appelée sans argument →
ADC fournit l'identité (SA `prt-prod-backend-sa` attachée à Cloud Run en
prod, `gcloud auth application-default login` en local). La vérification
des JWT Firebase se fait contre les certs publics Google, aucun rôle IAM
Firebase requis sur la SA.

## Signed URLs (V4 PUT, 15min)

Même contrainte qu'au-dessus : pas de clé JSON pour signer. On utilise
`Blob.generate_signed_url(service_account_email=..., access_token=...)`
qui délègue la signature à l'API IAM Credentials (`signBlob`). Cela
requiert `roles/iam.serviceAccountTokenCreator` sur la SA backend
ciblant elle-même (self-impersonation, ajouté dans
`infra/envs/prod/iam_backend.tf`).

## Configuration (env vars)

| Var | Source | Défaut | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ADC / Cloud Run | — | project_id GCP. |
| `PRT_GCP_REGION` | env | `europe-west1` | Région BQ + Cloud Run. |
| `PRT_ENV` | env | `dev` | `dev` ou `prod`. Active certaines log levels en plus. |
| `PRT_LOG_LEVEL` | env | `INFO` | structlog level. |
| `PRT_OPENAPI_ENABLED` | env | `true` | Si `false`, désactive `/docs` et `/openapi.json`. |
| `PRT_CORS_ORIGINS` | env | `*` | CSV des origines autorisées (CORS). `*` désactive `allow_credentials`. |
| `PRT_BQ_DATASET_SILVER` | env | `prt_prod_silver` | Dataset Silver. |
| `PRT_BQ_DATASET_GOLD` | env | `prt_prod_gold` | Dataset Gold. |
| `PRT_BQ_TABLE_CATALOGUE` | env | `catalogue_produits` | Table catalogue produits. |
| `PRT_GCS_BUCKET_BRONZE` | env | — | Bucket bronze pour les tickets. |
| `PRT_SIGNED_URL_TTL_MIN` | env | `15` | TTL des Signed URLs en minutes. |
| `PRT_PG_HOST` | env | `127.0.0.1` | Private IP Cloud SQL (prod) ou proxy local. |
| `PRT_PG_PORT` | env | `5432` | — |
| `PRT_PG_DB` | env | `price_tracker` | — |
| `PRT_PG_USER` | env | `pt_app` | — |
| `PRT_PG_PASSWORD` | **secret** | — | Cloud SQL password (Secret Manager en prod). |
| `PRT_PG_POOL_SIZE` | env | `4` | Taille pool SQLAlchemy. |
| `PRT_AUTH_DISABLE` | env | `false` | **DEV ONLY** : bypass Firebase Auth (uid=`dev-bypass`). |

## Développement local

```bash
cd backend
uv sync

# Démarrer cloud-sql-proxy (binaire dans infra/envs/prod/)
../infra/envs/prod/cloud-sql-proxy \
  price-tracker-prod-01:europe-west1:prt-prod-sql-main --port=5432 &

# Récupérer le password Cloud SQL
export PRT_PG_PASSWORD=$(gcloud secrets versions access latest \
  --secret=prt-prod-cloudsql-password --project=price-tracker-prod-01)

# ADC pour Firebase + GCS + BQ
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=price-tracker-prod-01

# Migrations (1ère fois)
DATABASE_URL="postgresql+asyncpg://pt_app:${PRT_PG_PASSWORD}@127.0.0.1:5432/price_tracker" \
  uv run alembic upgrade head

# Run (bypass auth pour tests rapides)
export PRT_AUTH_DISABLE=1
export PRT_PG_HOST=127.0.0.1
export PRT_GCS_BUCKET_BRONZE=price-tracker-prod-01-bronze
uv run uvicorn pricetracker_api.main:app --reload --port 8080

# Smoke
curl http://localhost:8080/healthz
curl http://localhost:8080/docs
```

## Tests

```bash
uv run pytest
```

Les tests d'intégration utilisent `testcontainers` avec l'image
`pgvector/pgvector:pg15` (extension `vector` préinstallée). Firebase Auth
et BigQuery sont mockés.

## Build & deploy (production)

Voir `docs/phase-07-handoff.md` §"Workflow programmatique récap" pour les
commandes exactes (`gcloud builds submit`, bump `backend_image_tag`,
`terraform plan/apply`, smoke test).
