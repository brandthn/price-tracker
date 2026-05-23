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
# Ingress public (`all`) : sera durci en internal-and-cloud-load-balancing
# en Phase 7 quand le Load Balancer + custom domain seront en place.
module "run_backend" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-backend"
  image                 = local.cloud_run_skeleton_image
  service_account_email = module.iam.emails["backend"]

  min_instances = 0
  max_instances = 3
  cpu           = "1"
  memory        = "512Mi"

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_ALL"

  # Skeleton hello accessible pour valider le déploiement de bout en bout.
  # Phase 7 : passer à false dès que Firebase Auth est en place.
  allow_unauthenticated = true

  labels = merge(var.labels, { component = "backend" })
}

# --- Worker OCR (Phase 8) ------------------------------------------------
# Déclenché par Pub/Sub push subscription sur `ticket-uploaded` (cf.
# pubsub.tf). Ingress restreint au plan interne + GCP services.
# Mémoire = 512Mi en skeleton ; à relever à 2Gi en Phase 8 (PaddleOCR / Gemini).
module "run_worker_ocr" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr"
  image                 = local.cloud_run_skeleton_image
  service_account_email = module.iam.emails["worker"]

  min_instances = 0
  max_instances = 5
  cpu           = "1"
  memory        = "512Mi"

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  labels = merge(var.labels, { component = "worker-ocr" })
}

# --- Worker Ingestion (Phase 6.1) ----------------------------------------
# Cron quotidien (03h UTC) — pull du snapshot Open Prices HuggingFace,
# upload Bronze parquet, MERGE BQ `silver.open_prices_clean`.
#
# Tailles ajustées Phase 6.1 :
# - timeout 1800s : parquet HF ~150MB → transform pyarrow → upload GCS → BQ MERGE.
#   30 min est suffisant en steady state ; reste large vs cold start HF.
# - memory 2Gi : pyarrow peut materialiser tout le parquet en RAM lors de la
#   normalisation. 1Gi est trop juste si OFF étoffe le dataset.
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
  image                 = local.cloud_run_skeleton_image
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 1
  cpu             = "2"
  memory          = "2Gi"
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
  image                 = local.cloud_run_skeleton_image
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

    PRT_OFF_BASE_URL         = "https://world.openfoodfacts.org"
    PRT_OFF_RATE_RPM         = "15"
    PRT_OFF_MAX_EANS_PER_RUN = "2000"
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
