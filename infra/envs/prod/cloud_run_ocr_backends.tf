# Cloud Run — 6 workers OCR « un backend = un worker ».
#
# Chaque backend historiquement encapsulé dans `dev_ocr` (paddle, ppocrv4,
# moondream, groq, receipt-vlm-500m, ocr-vlm from-scratch) devient un service
# Cloud Run indépendant, avec le MÊME contrat que worker-ocr / worker-ocr-llm :
# Pub/Sub push {ticket_id} → GET image GCS → OCR → écriture atomique Cloud SQL.
#
# Fichier 100 % ADDITIF : aucune ressource de cloud_run.tf n'est modifiée. Les
# références croisées (local.cloud_run_skeleton_image, local.cloud_run_subnet,
# module.iam, module.cloud_sql_main, module.secrets, module.bucket_models) sont
# en LECTURE SEULE — Terraform partage un namespace plat par répertoire.
#
# Le pipeline commun est packagé dans libs/pricetracker_receipt_pipeline ;
# `timeout_seconds = 540` reste < ack_deadline 600s de la subscription.

# --- Backend PaddleOCR ----------------------------------------------------
# cpu 2 / memory 4Gi : inférence CPU locale (paddlepaddle + modèles fr baked
# dans l'image). Le worker-ocr tier-1 tourne à 2Gi mais délègue à une API
# distante ; ici tout est local, d'où la marge. >2Gi impose >=2 vCPU.
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

  env = merge(local.ocr_backend_common_env, {
    PRT_OCR_ENGINE_LABEL       = "paddleocr"
    RECEIPT_OCR_MAX_IMAGE_SIDE = "1280"
    RECEIPT_OCR_CPU_THREADS    = "2"
  })

  secret_env = local.ocr_backend_common_secret_env

  labels = merge(var.labels, { component = "worker-ocr-paddle" })
}

# --- Backend PP-OCRv4 mobile ---------------------------------------------
# Même profil que paddle (mêmes libs), image réduite à 640px → plus rapide.
module "run_worker_ocr_ppocrv4" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-ppocrv4"
  image                 = var.worker_ocr_ppocrv4_image_tag == "skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-ocr-ppocrv4:${var.worker_ocr_ppocrv4_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 3
  cpu             = "2"
  memory          = "4Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = merge(local.ocr_backend_common_env, {
    PRT_OCR_ENGINE_LABEL               = "ppocrv4"
    RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE = "640"
    RECEIPT_OCR_CPU_THREADS            = "2"
  })

  secret_env = local.ocr_backend_common_secret_env

  labels = merge(var.labels, { component = "worker-ocr-ppocrv4" })
}

# --- Backend VLM Moondream 0.5B (poids locaux) ---------------------------
# cpu 2 / memory 2Gi : poids int8 ~600Mo en /tmp (tmpfs, compté dans la RAM)
# + runtime moondream. Téléchargés depuis le bucket models au cold start.
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
  memory          = "2Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = merge(local.ocr_backend_common_env, {
    PRT_OCR_ENGINE_LABEL = "moondream-0.5b"

    # Bootstrap des poids au démarrage (lifespan) : worker-sa a déjà
    # objectViewer sur le bucket models (cf. storage.tf) → aucun IAM à ajouter.
    PRT_MODEL_GCS_URI   = "gs://${module.bucket_models.name}/${var.ocr_vlm_moondream_model_gcs_uri}"
    PRT_MODEL_LOCAL_DIR = "/tmp/models"

    RECEIPT_VLM_MODE        = "transcribe"
    RECEIPT_VLM_MAX_RETRIES = "2"
  })

  secret_env = local.ocr_backend_common_secret_env

  labels = merge(var.labels, { component = "worker-ocr-vlm-moondream" })
}

# --- Backend VLM Groq (API cloud) ----------------------------------------
# cpu 1 / memory 1Gi : aucune inférence locale, le worker attend l'API Groq.
# Seul worker de cette famille à consommer un secret applicatif.
module "run_worker_ocr_vlm_groq" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-vlm-groq"
  image                 = var.worker_ocr_vlm_groq_image_tag == "skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-ocr-vlm-groq:${var.worker_ocr_vlm_groq_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 3
  cpu             = "1"
  memory          = "1Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = merge(local.ocr_backend_common_env, {
    PRT_OCR_ENGINE_LABEL = "groq-llama4-scout"
    # GroqProvider refuse de démarrer dans un autre mode.
    RECEIPT_VLM_MODE = "json"
  })

  secret_env = merge(local.ocr_backend_common_secret_env, {
    GROQ_API_KEY = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-groq-api-key"]
      version = "latest"
    }
  })

  labels = merge(var.labels, { component = "worker-ocr-vlm-groq" })
}

# --- Backend receipt-vlm-500m (CLIP+SmolLM, poids locaux) ----------------
# cpu 4 / memory 16Gi : le checkpoint mergé (~1,8 Go) est téléchargé dans /tmp
# (tmpfs = RAM), puis chargé en fp32 avec instanciation des backbones → pic à
# plusieurs Go. Cloud Run exige >=4 vCPU au-delà de 8Gi. Inférence CPU lente :
# max_instances=2 pour plafonner le coût.
module "run_worker_ocr_vlm_receipt" {
  source = "../../modules/cloud_run"

  project_id            = var.project_id
  region                = var.region
  name                  = "${var.name_prefix}-worker-ocr-vlm-receipt"
  image                 = var.worker_ocr_vlm_receipt_image_tag == "skeleton" ? local.cloud_run_skeleton_image : "${module.artifact_registry.docker_registry_url}/worker-ocr-vlm-receipt:${var.worker_ocr_vlm_receipt_image_tag}"
  service_account_email = module.iam.emails["worker"]

  min_instances   = 0
  max_instances   = 2
  cpu             = "4"
  memory          = "16Gi"
  timeout_seconds = 540

  vpc_subnet = local.cloud_run_subnet
  vpc_egress = "PRIVATE_RANGES_ONLY"
  ingress    = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  env = merge(local.ocr_backend_common_env, {
    PRT_OCR_ENGINE_LABEL = "receipt-vlm-500m"

    PRT_MODEL_GCS_URI   = "gs://${module.bucket_models.name}/${var.ocr_vlm_receipt_model_gcs_uri}"
    PRT_MODEL_LOCAL_DIR = "/tmp/models"

    # Le modèle est entraîné pour émettre le JSON canonique : pas d'autre mode.
    # Les backbones HF sont baked dans l'image (HF_HUB_OFFLINE=1) car
    # vpc_egress=PRIVATE_RANGES_ONLY interdit l'accès au hub.
    RECEIPT_VLM_MODE = "json"
  })

  secret_env = local.ocr_backend_common_secret_env

  labels = merge(var.labels, { component = "worker-ocr-vlm-receipt" })
}

# --- Backend OCR-VLM from-scratch ----------------------------------------
# cpu 2 / memory 4Gi : modèle maison compact (embed 256, 4+4 couches), mais
# décodage glouton jusqu'à 640 tokens sur CPU. max_instances=2 (coût + le
# modèle n'a été évalué que sur Kaggle : montée en charge à surveiller).
# DEUX fichiers de poids : checkpoint .pt + tokenizer .json.
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

  env = merge(local.ocr_backend_common_env, {
    PRT_OCR_ENGINE_LABEL = "ocr-vlm-scratch"

    PRT_MODEL_GCS_URI     = "gs://${module.bucket_models.name}/${var.ocr_vlm_scratch_model_gcs_uri}"
    PRT_TOKENIZER_GCS_URI = "gs://${module.bucket_models.name}/${var.ocr_vlm_scratch_tokenizer_gcs_uri}"
    PRT_MODEL_LOCAL_DIR   = "/tmp/models"
  })

  secret_env = local.ocr_backend_common_secret_env

  labels = merge(var.labels, { component = "worker-ocr-vlm-scratch" })
}

# --- Env / secrets communs aux 6 workers ----------------------------------
locals {
  ocr_backend_common_env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    PRT_GCP_REGION       = var.region

    PRT_PG_HOST      = module.cloud_sql_main.private_ip_address
    PRT_PG_PORT      = "5432"
    PRT_PG_DB        = module.cloud_sql_main.db_name
    PRT_PG_USER      = module.cloud_sql_main.db_user
    PRT_PG_POOL_SIZE = "4"

    # Audience laissée vide → fallback sur x-forwarded-host (cf. worker/auth.py),
    # évite le cycle TF service→env→service. L'allowlist worker-sa fait la
    # défense en profondeur.
    PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS = module.iam.emails["worker"]
  }

  ocr_backend_common_secret_env = {
    PRT_PG_PASSWORD = {
      secret  = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]
      version = "latest"
    }
  }
}

# --- IAM : worker-sa peut invoquer les 6 nouveaux services -----------------
# Requis pour Pub/Sub push → Cloud Run (worker-sa porte l'identité OIDC).
# Ressource DISTINCTE de `worker_sa_invoker` (cloud_run.tf) : on n'ajoute pas de
# clés à son for_each, donc les 6 services existants ne sont pas replanifiés.
locals {
  ocr_backend_worker_services = toset([
    module.run_worker_ocr_paddle.name,
    module.run_worker_ocr_ppocrv4.name,
    module.run_worker_ocr_vlm_moondream.name,
    module.run_worker_ocr_vlm_groq.name,
    module.run_worker_ocr_vlm_receipt.name,
    module.run_worker_ocr_vlm_scratch.name,
  ])
}

resource "google_cloud_run_v2_service_iam_member" "ocr_backend_worker_sa_invoker" {
  for_each = local.ocr_backend_worker_services

  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = local.worker_sa
}
