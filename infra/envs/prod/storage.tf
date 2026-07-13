# bucket bronze : tickets users + snapshots HF. backend+workers objectAdmin.
# CORS ouvert pour l'upload signed url depuis le navigateur.
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

# bucket silver : donnees nettoyees. workers objectAdmin, backend viewer.
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

# bucket models : poids OCR/embeddings versionnes. worker viewer.
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
