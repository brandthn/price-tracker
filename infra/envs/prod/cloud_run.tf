locals {
  cloud_run_skeleton_image = "us-docker.pkg.dev/cloudrun/container/hello"
  cloud_run_subnet          = module.network.subnet_name
}

# backend fastapi
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

    PRT_ENV          = var.backend_auth_enabled ? "prod" : "dev"
    PRT_AUTH_DISABLE = var.backend_auth_enabled ? "0" : "1"

    PRT_LOG_LEVEL       = "INFO"
    PRT_OPENAPI_ENABLED = "true"

    PRT_CORS_ORIGINS = "*"

    PRT_BQ_DATASET_SILVER  = local.bq_silver_dataset
    PRT_BQ_DATASET_GOLD    = "${replace(var.name_prefix, "-", "_")}_gold"
    PRT_BQ_TABLE_CATALOGUE = google_bigquery_table.catalogue_produits.table_id

    PRT_GCS_BUCKET_BRONZE  = module.bucket_bronze.name
    PRT_SIGNED_URL_TTL_MIN = "15"

    PRT_PG_HOST      = module.cloud_sql_main.private_ip_address
    PRT_PG_PORT      = "5432"
    PRT_PG_DB        = module.cloud_sql_main.db_name
    PRT_PG_USER      = module.cloud_sql_main.db_user
    PRT_PG_POOL_SIZE = "4"

    PRT_OCR_MOONDREAM_TOPIC = module.pubsub.topics["ocr-vlm-moondream"].name
    PRT_OCR_RETRY_TOPIC     = module.pubsub.topics["ocr-retry"].name
    PRT_MAX_OCR_ATTEMPTS    = "4"
  }

  secret_env = {
    PRT_PG_PASSWORD = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]
      version = "latest"
    }
  }

  labels = merge(var.labels, { component = "backend" })
}

# worker ocr (groq, push sur ticket-uploaded)
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

# worker ocr tier-2 / llm (re-ocr sur retry, topic ocr-retry)
module "run_worker_ocr_llm" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-llm"
  image                 = "${module.artifact_registry.docker_registry_url}/worker-ocr-llm:${var.worker_ocr_llm_image_tag}"
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

    PRT_OCR_MODEL        = "gemini-2.5-flash"
    PRT_OCR_ENGINE_LABEL = "gemini"
    PRT_VERTEX_LOCATION  = "global"

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

  labels = merge(var.labels, { component = "worker-ocr-llm" })
}

# worker ocr paddle (inference cpu locale, 4Gi)
module "run_worker_ocr_paddle" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-paddle"
  image                 = var.worker_ocr_paddle_image_tag == "skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-ocr-paddle:${var.worker_ocr_paddle_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 3
  cpu             = "2"
  memory          = "4Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    PRT_GCP_REGION       = var.region

    PRT_OCR_ENGINE_LABEL       = "paddleocr"
    RECEIPT_OCR_MAX_IMAGE_SIDE = "1280"
    RECEIPT_OCR_CPU_THREADS    = "2"

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

  labels = merge(var.labels, { component = "worker-ocr-paddle" })
}

# worker ocr vlm moondream (poids .mf 673Mo depuis bucket models, 4Gi sinon OOM)
module "run_worker_ocr_vlm_moondream" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-vlm-moondream"
  image                 = var.worker_ocr_vlm_moondream_image_tag == "skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-ocr-vlm-moondream:${var.worker_ocr_vlm_moondream_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 3
  cpu             = "2"
  memory          = "4Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    PRT_GCP_REGION       = var.region

    PRT_OCR_ENGINE_LABEL = "moondream-0.5b"
    PRT_MODEL_GCS_URI    = "gs://${module.bucket_models.name}/${var.ocr_vlm_moondream_model_gcs_uri}"
    PRT_MODEL_LOCAL_DIR  = "/tmp/models"

    RECEIPT_VLM_MODE        = "transcribe"
    RECEIPT_VLM_MAX_RETRIES = "2"

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

  labels = merge(var.labels, { component = "worker-ocr-vlm-moondream" })
}

# worker ocr vlm from-scratch (checkpoint .pt + tokenizer .json depuis bucket models)
module "run_worker_ocr_vlm_scratch" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-vlm-scratch"
  image                 = var.worker_ocr_vlm_scratch_image_tag == "skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-ocr-vlm-scratch:${var.worker_ocr_vlm_scratch_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 2
  cpu             = "2"
  memory          = "4Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    PRT_GCP_REGION       = var.region

    PRT_OCR_ENGINE_LABEL  = "ocr-vlm-scratch"
    PRT_MODEL_GCS_URI     = "gs://${module.bucket_models.name}/${var.ocr_vlm_scratch_model_gcs_uri}"
    PRT_TOKENIZER_GCS_URI = "gs://${module.bucket_models.name}/${var.ocr_vlm_scratch_tokenizer_gcs_uri}"
    PRT_MODEL_LOCAL_DIR   = "/tmp/models"

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

  labels = merge(var.labels, { component = "worker-ocr-vlm-scratch" })
}

# worker ingestion (cron 03h utc, snapshot HF -> bronze -> BQ silver)
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
    # FR metropole + DOM-TOM
    PRT_FILTER_COUNTRY_CODES = "FR,GP,GF,MQ,RE,YT,PM,MF,BL,WF,NC,PF"

    # audience vide -> fallback url resolue via x-forwarded-host (auth.py)
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

# worker off (cron 04h utc, enrichissement EAN OFF + embeddings vertex)
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
    # 13 rpm ~ 4.6s/req, sous la limite 15 rpm/IP (anti-ban)
    PRT_OFF_RATE_RPM         = "13"
    PRT_OFF_MAX_EANS_PER_RUN = "200"
    PRT_OFF_RUN_TIMEOUT_S    = "3500"
    PRT_OFF_HTTP_TIMEOUT_S   = "20"
    PRT_OFF_MAX_RETRIES      = "4"

    PRT_VERTEX_MODEL      = "text-embedding-004"
    PRT_VERTEX_BATCH      = "250"
    PRT_VERTEX_TASK_TYPE  = "SEMANTIC_SIMILARITY"
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

# worker indices (cron 05h utc, TRUNCATE+INSERT tables BQ gold)
module "run_worker_indices" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-indices"
  image                 = var.worker_indices_image_tag == "phase9-skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-indices:${var.worker_indices_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 1
  cpu             = "1"
  memory          = "1Gi"
  timeout_seconds = 900

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT     = var.project_id
    PRT_GCP_REGION           = var.region
    PRT_BQ_DATASET_SILVER    = local.bq_silver_dataset
    PRT_BQ_DATASET_GOLD      = local.bq_gold_dataset
    PRT_BQ_TABLE_OPEN_PRICES = google_bigquery_table.open_prices_clean.table_id
    PRT_BQ_TABLE_AGGREGATS   = google_bigquery_table.aggregats_enseignes.table_id
    PRT_BQ_TABLE_INDICES     = google_bigquery_table.indices_inflation.table_id
    PRT_BQ_TABLE_RANKINGS    = google_bigquery_table.rankings_produits.table_id
    PRT_BQ_TABLE_ANOMALIES   = google_bigquery_table.anomalies_detected.table_id
    PRT_BQ_LOCATION          = "EU"

    PRT_INDICES_MIN_OBSERVATIONS       = "3"
    PRT_INDICES_WINDOW_WEEKS_AGGREGATS = "12"
    PRT_INDICES_WINDOW_WEEKS_RANKINGS  = "8"
    PRT_INDICES_Z_THRESHOLD            = "2.0"
    PRT_INDICES_TOP_N_RANKINGS         = "500"

    PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS = module.iam.emails["worker"]
  }

  labels = merge(var.labels, { component = "worker-indices" })
}

# frontend next.js (ingress public, pas de vpc egress)
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
    NEXT_PUBLIC_API_BASE_URL = "https://prt-prod-backend-y5iagyfila-ew.a.run.app"
    NEXT_PUBLIC_DEMO_BEARER  = "demo"
    NEXT_TELEMETRY_DISABLED  = "1"
  }

  labels = merge(var.labels, { component = "frontend" })
}

# worker alertes (cron 07h utc, V1 = rapport json sur bronze, pas de push FCM)
module "run_worker_alertes" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-alertes"
  image                 = var.worker_alertes_image_tag == "phase9-skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-alertes:${var.worker_alertes_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 1
  cpu             = "1"
  memory          = "512Mi"
  timeout_seconds = 300

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = {
    GOOGLE_CLOUD_PROJECT   = var.project_id
    PRT_GCP_REGION         = var.region
    PRT_BQ_DATASET_GOLD    = local.bq_gold_dataset
    PRT_BQ_TABLE_RANKINGS  = google_bigquery_table.rankings_produits.table_id
    PRT_BQ_TABLE_ANOMALIES = google_bigquery_table.anomalies_detected.table_id
    PRT_BQ_LOCATION        = "EU"

    PRT_ALERTS_BUCKET = module.bucket_bronze.name
    PRT_ALERTS_PREFIX = "alerts"

    PRT_ALERTES_TOP_RANKINGS   = "50"
    PRT_ALERTES_MIN_PCT_CHANGE = "0.05"
    PRT_ALERTES_TOP_ANOMALIES  = "100"
    PRT_ALERTES_LOOKBACK_WEEKS = "2"

    PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS = module.iam.emails["worker"]
  }

  labels = merge(var.labels, { component = "worker-alertes" })
}

# worker-sa invoker sur les services workers (scheduler + pubsub push)
locals {
  worker_run_services = toset([
    module.run_worker_ocr.name,
    module.run_worker_ocr_llm.name,
    module.run_worker_ocr_paddle.name,
    module.run_worker_ocr_vlm_moondream.name,
    module.run_worker_ocr_vlm_scratch.name,
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
