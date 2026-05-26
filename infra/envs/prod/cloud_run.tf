# Cloud Run services — Phase 5 SKELETON.
#
# Tous les services pointent vers l'image hello officielle Google
# (us-docker.pkg.dev/cloudrun/container/hello). Aucun code applicatif n'est
# encore embarqué ; ces ressources servent à valider :
#   - la tuyauterie IAM (Cloud Scheduler / Pub/Sub → Cloud Run via OIDC)
#   - le Direct VPC egress (subnet prt-subnet-ew1)
#   - les conventions de nommage et labels
#
# Chaque phase suivante remplacera l'image par l'image AR `prt-prod-docker/<svc>:<sha>`
# via un `terraform apply` (ou via le workflow GH Actions une fois la Phase 3 livrée).
#
# Plafonds max_instances volontairement bas — Free Trial 300 $, scale-out
# accidentel = facture exponentielle. À relever à chaud quand on aura mesuré
# la charge réelle.

locals {
  # Image GA recommandée par Google depuis fin 2024. gcr.io/cloudrun/hello
  # marche encore via redirect mais est en sunset progressif.
  cloud_run_skeleton_image = "us-docker.pkg.dev/cloudrun/container/hello"

  # Subnet sur lequel tous les Cloud Run s'attachent en Direct VPC egress.
  # Le module cloud_run accepte un nom (résolu dans même project+region) ou
  # un self_link ; on passe le nom pour la lisibilité du plan.
  cloud_run_subnet = module.network.subnet_name
}

# --- Backend FastAPI (Phase 7) -------------------------------------------
# Ingress public (`all`) : le frontend Next.js (Vercel + clients mobiles) appelle
# l'API par HTTPS. La sécurité repose sur :
#   - Firebase Auth (JWT Bearer) côté code applicatif
#   - CORS contrôlé par PRT_CORS_ORIGINS
#   - Cloud SQL atteint en private IP via Direct VPC egress (RFC1918 only)
# Durcissement Phase 11 : Load Balancer + Cloud Armor, ingress = INTERNAL_LOAD_BALANCER.
#
# memory=1Gi : asyncpg + SQLAlchemy + firebase-admin + BigQuery client. 512Mi est
# tendu au cold-start. CPU=1 (workload I/O-bound).
#
# allow_unauthenticated=true : indispensable au frontend public (la JWT Auth se
# fait au niveau applicatif, pas IAM Cloud Run). À garder true en prod.
module "run_backend" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-backend"
  image                 = "${module.artifact_registry.docker_registry_url}/backend:${var.backend_image_tag}"
  service_account_email = module.iam.emails["backend"]

  min_instances   = 0
  max_instances   = 3
  cpu             = "1"
  memory          = "1Gi"
  timeout_seconds = 60

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_ALL"

  allow_unauthenticated = true

  env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    PRT_GCP_REGION       = var.region

    # Mode démo — bypasse la vérification Firebase JWT.
    # Maintenu jusqu'à Phase 10 (frontend Next.js + Firebase Web SDK).
    # Revert : mettre PRT_ENV=prod + PRT_AUTH_DISABLE=0 (ou supprimer la ligne).
    PRT_ENV          = "dev"
    PRT_AUTH_DISABLE = "1"

    PRT_LOG_LEVEL       = "INFO"
    PRT_OPENAPI_ENABLED = "true"

    # CORS : wildcard temporaire jusqu'au domaine fixe frontend (Phase 10).
    # Credentials cookies désactivés côté FastAPI (allow_credentials=False) donc
    # `*` est sûr.
    PRT_CORS_ORIGINS = "*"

    # BigQuery — observatoire (Gold) + catalogue (Silver)
    PRT_BQ_DATASET_SILVER  = local.bq_silver_dataset
    PRT_BQ_DATASET_GOLD    = "${replace(var.name_prefix, "-", "_")}_gold"
    PRT_BQ_TABLE_CATALOGUE = google_bigquery_table.catalogue_produits.table_id

    # GCS — Signed URL upload tickets (V4 PUT, 15 min TTL)
    PRT_GCS_BUCKET_BRONZE  = module.bucket_bronze.name
    PRT_SIGNED_URL_TTL_MIN = "15"

    # Cloud SQL — Direct VPC egress vers private IP
    PRT_PG_HOST      = module.cloud_sql_main.private_ip_address
    PRT_PG_PORT      = "5432"
    PRT_PG_DB        = module.cloud_sql_main.db_name
    PRT_PG_USER      = module.cloud_sql_main.db_user
    PRT_PG_POOL_SIZE = "4"
  }

  secret_env = {
    PRT_PG_PASSWORD = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]
      version = "latest"
    }
  }

  labels = merge(var.labels, { component = "backend" })
}

# --- Worker OCR (Phase 8) ------------------------------------------------
# Déclenché par Pub/Sub push subscription sur `ticket-uploaded` (cf.
# pubsub.tf). Ingress restreint au plan interne + GCP services.
# Mémoire = 512Mi en skeleton ; à relever à 2Gi en Phase 8 (PaddleOCR / Gemini).
# --- Worker OCR (Phase 8) -------------------------------------------------
# Déclenché par Pub/Sub push (subscription ticket-uploaded-ocr-push).
# Reçoit le chemin GCS du ticket, fait OCR via Groq LLaMA 4 Scout, écrit
# dans Cloud SQL tickets + prix_extraits.
#
# Ressources :
# - memory 2Gi : Groq SDK + structlog + asyncpg ; le modèle tourne côté Groq
#   API (aucune inférence locale) → 2Gi suffit.
# - cpu "2" : I/O bound sur l'appel Groq, mais 2 vCPU pour traiter plusieurs
#   images en parallèle sans saturation.
# - timeout 540s : < ack_deadline 600s (marge pour l'ACK Pub/Sub final).
module "run_worker_ocr" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr"
  image                 = "${module.artifact_registry.docker_registry_url}/worker-ocr:${var.worker_ocr_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 5
  cpu             = "2"
  memory          = "2Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    PRT_GCP_REGION       = var.region
    PRT_BRONZE_BUCKET    = module.bucket_bronze.name
    PRT_OCR_ENGINE       = "groq"

    PRT_PG_HOST      = module.cloud_sql_main.private_ip_address
    PRT_PG_PORT      = "5432"
    PRT_PG_DB        = module.cloud_sql_main.db_name
    PRT_PG_USER      = module.cloud_sql_main.db_user
    PRT_PG_POOL_SIZE = "4"

    PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS = module.iam.emails["worker"]
  }

  secret_env = {
    PRT_PG_PASSWORD = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]
      version = "latest"
    }
    GROQ_API_KEY = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-groq-api-key"]
      version = "latest"
    }
  }

  labels = merge(var.labels, { component = "worker-ocr" })
}

# --- Worker Ingestion (Phase 6.1) ----------------------------------------
# Cron quotidien (03h UTC) — pull du snapshot Open Prices HuggingFace,
# upload Bronze parquet, MERGE BQ `silver.open_prices_clean`.
#
# Tailles ajustées Phase 6.1 :
# - timeout 1800s : parquet HF ~25MB compressé → transform pyarrow → upload GCS → BQ MERGE.
#   30 min est suffisant en steady state ; reste large vs cold start HF.
# - memory 4Gi : observé OOM kill à 2Gi le 2026-05-23 sur un parquet de 25MB on-disk —
#   le pipeline maintient en parallèle raw_table + intermediate pandas (cleaner +
#   enrichments + IQR numpy) + clean_table + rejections_table ; après overhead
#   sandbox Cloud Run + uvicorn + libs (~500-700MB), 2Gi laissait ≈1.3Gi pour data,
#   insuffisant. 4Gi donne ≈3× de marge et anticipe la croissance du dataset HF.
# - cpu 2 : transform pyarrow CPU-bound, le doublement raccourcit le run et
#   ne coûte que sur la durée de cold-start (scale-to-zero entre runs).
#
# Image reste skeleton (hello) jusqu'au premier `gcloud builds submit` +
# bump de `image` Phase 6.1 (cf. docs/phase-06-handoff.md §Déploiement).
module "run_worker_ingestion" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ingestion"
  image                 = "${module.artifact_registry.docker_registry_url}/worker-ingestion:${var.worker_ingestion_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 1
  cpu             = "2"
  memory          = "4Gi"
  timeout_seconds = 1800

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT     = var.project_id
    PRT_GCP_REGION           = var.region
    PRT_BRONZE_BUCKET        = "${var.project_id}-bronze"
    PRT_BQ_DATASET_SILVER    = local.bq_silver_dataset
    PRT_BQ_TABLE_OPEN_PRICES = google_bigquery_table.open_prices_clean.table_id
    PRT_BQ_TABLE_REJECTIONS  = google_bigquery_table.open_prices_rejections.table_id
    PRT_HF_DATASET           = "openfoodfacts/open-prices"
    PRT_HF_FILENAME          = "prices.parquet"
    # Pays acceptés par le cleaner : FR métropole + DOM-TOM. CSV pour rester simple
    # côté pydantic-settings. Le worker convertit en set() au load.
    PRT_FILTER_COUNTRY_CODES = "FR,GP,GF,MQ,RE,YT,PM,MF,BL,WF,NC,PF"

    # OIDC : on laisse l'audience vide → le code fallback sur l'URL résolue
    # depuis `x-forwarded-host` (cf. auth.py). Évite le cycle TF
    # service→env→service. L'allowlist du worker-sa fait la défense en
    # profondeur (Cloud Run a déjà refusé tout caller non OIDC en amont).
    PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS = module.iam.emails["worker"]
  }

  secret_env = {
    HF_TOKEN = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-hf-token"]
      version = "latest"
    }
  }

  labels = merge(var.labels, { component = "worker-ingestion" })
}

# --- Worker OFF (Phase 6.2) ----------------------------------------------
# Cron quotidien (04h UTC) — enrichissement EAN via OpenFoodFacts +
# embeddings Vertex AI text-embedding-004 → BQ `silver.catalogue_produits`
# + Cloud SQL `products` (pgvector 768).
#
# Tailles ajustées Phase 6.2 :
# - timeout 3600s : max Cloud Run gen2. À 15 req/min OFF, ≈800 EAN max par run.
#   Le worker s'auto-arrête à PRT_OFF_RUN_TIMEOUT_S=3500s pour ne pas se faire
#   killer brutalement (laisse marge pour flush BQ + pg).
# - memory 1Gi : asyncpg + httpx + Vertex SDK ; 512Mi est tendu avec le SDK
#   aiplatform qui charge plusieurs deps lourdes.
# - cpu 1 : workload I/O-bound (OFF + Vertex + pg), pas de CPU spike.
#
# Image reste skeleton (hello) jusqu'au premier build Phase 6.2.
module "run_worker_off" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-off"
  image                 = "${module.artifact_registry.docker_registry_url}/worker-off:${var.worker_off_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 1
  cpu             = "1"
  memory          = "1Gi"
  timeout_seconds = 3600

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT     = var.project_id
    PRT_GCP_REGION           = var.region
    PRT_BQ_DATASET_SILVER    = local.bq_silver_dataset
    PRT_BQ_TABLE_OPEN_PRICES = google_bigquery_table.open_prices_clean.table_id
    PRT_BQ_TABLE_CATALOGUE   = google_bigquery_table.catalogue_produits.table_id

    PRT_OFF_BASE_URL = "https://world.openfoodfacts.org"
    # 13 rpm = 4.6s/req : marge anti-ban vs la limite officielle 15 rpm/IP.
    # Cf. docs/OFF_API_Specification_PriceTracker.md §4 (reco "4.5s entre
    # chaque requête, ≈13 req/min sous la limite").
    PRT_OFF_RATE_RPM = "13"
    # 200 EANs/run nominal = ~15min à 4.6s/req. Compromis entre vitesse de
    # constitution catalogue et marge anti-ban. Reco OFF spec : tant qu'on
    # reste < 500/jour, l'API est conforme (au-delà : bulk download).
    PRT_OFF_MAX_EANS_PER_RUN = "200"
    PRT_OFF_RUN_TIMEOUT_S    = "3500"
    PRT_OFF_HTTP_TIMEOUT_S   = "20"
    PRT_OFF_MAX_RETRIES      = "4"

    PRT_VERTEX_MODEL      = "text-embedding-004"
    PRT_VERTEX_BATCH      = "250"
    PRT_VERTEX_TASK_TYPE  = "RETRIEVAL_DOCUMENT"
    PRT_VERTEX_OUTPUT_DIM = "768"

    PRT_PG_HOST      = module.cloud_sql_main.private_ip_address
    PRT_PG_PORT      = "5432"
    PRT_PG_DB        = module.cloud_sql_main.db_name
    PRT_PG_USER      = module.cloud_sql_main.db_user
    PRT_PG_POOL_SIZE = "4"

    PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS = module.iam.emails["worker"]
  }

  secret_env = {
    PRT_PG_PASSWORD = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]
      version = "latest"
    }
  }

  labels = merge(var.labels, { component = "worker-off" })
}

# --- Worker Indices (Phase 9.1) ------------------------------------------
# Cron quotidien (05h UTC) — calcul Laspeyres + détection anomalies.
module "run_worker_indices" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-indices"
  image                 = local.cloud_run_skeleton_image
  service_account_email = module.iam.emails["worker"]

  min_instances = 0
  max_instances = 1
  cpu           = "1"
  memory        = "512Mi"

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  labels = merge(var.labels, { component = "worker-indices" })
}

# --- Frontend Next.js (Phase 10) -----------------------------------------
# Ingress public : page consultable par n'importe qui via HTTPS.
# Pas de VPC egress : le front ne parle qu'au backend Cloud Run public,
# pas besoin de remonter dans le subnet privé.
#
# memory 512Mi : Next.js 16 standalone tourne autour de 200-300Mi RSS en
# steady state ; 512Mi laisse marge pour les pics de RSC.
# cpu "1" : I/O-bound (forward HTTP au backend), aucun calcul lourd côté front.
# timeout 30s : RSC en mode no-store → un appel BQ peut prendre ~3s cold,
# 30s couvre largement les cas pathologiques.
#
# Pas de VPC egress (vpc_subnet = null) : le front n'a aucune ressource
# privée à atteindre. Tous les appels backend partent en internet egress
# vers l'URL publique Cloud Run.
module "run_frontend" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-frontend"
  image                 = "${module.artifact_registry.docker_registry_url}/frontend:${var.frontend_image_tag}"
  service_account_email = module.iam.emails["frontend"]

  min_instances   = 0
  max_instances   = 3
  cpu             = "1"
  memory          = "512Mi"
  timeout_seconds = 30

  vpc_subnet = null
  ingress    = "INGRESS_TRAFFIC_ALL"

  allow_unauthenticated = true

  env = {
    # Runtime vars consommées côté Node (RSC) — le bundle client a sa propre
    # copie inlinée au moment de `next build` (cf. ARG dans frontend/Dockerfile).
    NEXT_PUBLIC_API_BASE_URL = "https://prt-prod-backend-y5iagyfila-ew.a.run.app"
    NEXT_PUBLIC_DEMO_BEARER  = "demo"

    # Désactive la télémétrie Vercel — pas besoin sur Cloud Run.
    NEXT_TELEMETRY_DISABLED = "1"
  }

  labels = merge(var.labels, { component = "frontend" })
}

# --- Worker Alertes (Phase 9.2) ------------------------------------------
# Cron quotidien (07h UTC) — push FCM sur produits en hausse.
module "run_worker_alertes" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-alertes"
  image                 = local.cloud_run_skeleton_image
  service_account_email = module.iam.emails["worker"]

  min_instances = 0
  max_instances = 1
  cpu           = "1"
  memory        = "512Mi"

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  labels = merge(var.labels, { component = "worker-alertes" })
}

# --- IAM : worker-sa peut invoquer les 5 services workers ----------------
# Requis pour : Cloud Scheduler → worker-{ingestion,off,indices,alertes}
# et Pub/Sub push → worker-ocr. La SA worker-sa porte l'identité OIDC dans
# les deux cas.
locals {
  worker_run_services = toset([
    module.run_worker_ocr.name,
    module.run_worker_ingestion.name,
    module.run_worker_off.name,
    module.run_worker_indices.name,
    module.run_worker_alertes.name,
  ])
}

resource "google_cloud_run_v2_service_iam_member" "worker_sa_invoker" {
  for_each = local.worker_run_services

  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = local.worker_sa
}
