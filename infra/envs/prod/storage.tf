# Bucket BRONZE — données brutes : tickets users (Backend signe PUT) +
# snapshots HuggingFace open-prices archivés par worker-ingestion.
# Backend et workers ont objectAdmin (lecture/écriture/suppression). Convention
# alignée avec Silver pour éviter d'ajuster les rôles à chaque nouveau pipeline.
#
# CORS : ouvert pour PUT/OPTIONS depuis le navigateur du frontend, sinon le
# preflight déclenché par `Content-Type: image/jpeg` bloque l'upload Signed URL.
# `origin = ["*"]` en démo Phase 10 — restreindre à l'URL Cloud Run frontend
# une fois stabilisée (cf. var.frontend_cors_origins ci-dessous).
module "bucket_bronze" {
  source = "../../modules/storage"

  project_id         = var.project_id
  name               = "${var.project_id}-bronze"
  location           = "EU"
  versioning_enabled = true
  lifecycle_rules    = local.data_lake_lifecycle
  labels             = merge(var.labels, { component = "bronze" })

  object_admins = [local.backend_sa, local.worker_sa]

  cors = [
    {
      origin          = var.frontend_cors_origins
      method          = ["GET", "PUT", "POST", "HEAD", "OPTIONS"]
      response_header = ["Content-Type", "ETag", "x-goog-resumable"]
      max_age_seconds = 3600
    }
  ]
}

# Bucket SILVER — données nettoyées (parquet OpenPrices, OFF, etc.).
# Workers d'ingestion écrivent (objectAdmin). Backend lit pour stats (viewer).
module "bucket_silver" {
  source = "../../modules/storage"

  project_id         = var.project_id
  name               = "${var.project_id}-silver"
  location           = "EU"
  versioning_enabled = false
  lifecycle_rules    = local.data_lake_lifecycle
  labels             = merge(var.labels, { component = "silver" })

  object_admins  = [local.worker_sa]
  object_viewers = [local.backend_sa]
}

# Bucket MODELS — poids des modèles OCR / embeddings versionnés.
# Pas de suppression auto sur les versions courantes. Worker = viewer.
module "bucket_models" {
  source = "../../modules/storage"

  project_id         = var.project_id
  name               = "${var.project_id}-models"
  location           = "EU"
  versioning_enabled = true
  lifecycle_rules    = local.models_lifecycle
  labels             = merge(var.labels, { component = "models" })

  object_viewers = [local.worker_sa]
}
