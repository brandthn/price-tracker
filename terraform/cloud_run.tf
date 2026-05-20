resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = var.artifact_repository_id
  description   = "Images Docker des workers Open Prices"
  format        = "DOCKER"
}

resource "google_service_account" "worker" {
  account_id   = "open-prices-worker"
  display_name = "Open Prices pipeline workers"
}

locals {
  worker_image_base = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

resource "google_project_iam_member" "worker_bq" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "worker_bq_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_storage_bucket_iam_member" "worker_bronze" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_storage_bucket_iam_member" "worker_signals" {
  bucket = google_storage_bucket.signals.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_storage_bucket_iam_member" "worker_artifacts" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_cloud_run_v2_service" "ingestion" {
  count    = var.create_cloud_run_services ? 1 : 0
  name     = "worker-ingestion"
  location = var.region
  template {
    service_account = google_service_account.worker.email
    timeout         = "900s"
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = "${local.worker_image_base}/worker-ingestion:${var.worker_image_tag}"
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.dataset_id
      }
      env {
        name  = "GCS_BRONZE_BUCKET"
        value = google_storage_bucket.bronze.name
      }
      env {
        name  = "GCS_SIGNALS_BUCKET"
        value = google_storage_bucket.signals.name
      }
      env {
        name  = "GCS_ARTIFACTS_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      resources {
        limits = { cpu = "1", memory = "2Gi" }
      }
    }
  }
  depends_on = [google_artifact_registry_repository.docker]
}

resource "google_cloud_run_v2_service" "off" {
  count    = var.create_cloud_run_services ? 1 : 0
  name     = "worker-off"
  location = var.region
  template {
    service_account = google_service_account.worker.email
    timeout         = "900s"
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = "${local.worker_image_base}/worker-off:${var.worker_image_tag}"
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.dataset_id
      }
      env {
        name  = "GCS_SIGNALS_BUCKET"
        value = google_storage_bucket.signals.name
      }
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
    }
  }
}

resource "google_cloud_run_v2_service" "indices" {
  count    = var.create_cloud_run_services ? 1 : 0
  name     = "worker-indices"
  location = var.region
  template {
    service_account = google_service_account.worker.email
    timeout         = "900s"
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = "${local.worker_image_base}/worker-indices:${var.worker_image_tag}"
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.dataset_id
      }
      env {
        name  = "GCS_SIGNALS_BUCKET"
        value = google_storage_bucket.signals.name
      }
      resources {
        limits = { cpu = "2", memory = "4Gi" }
      }
    }
  }
}

resource "google_cloud_run_v2_service" "alertes" {
  count    = var.create_cloud_run_services ? 1 : 0
  name     = "worker-alertes"
  location = var.region
  template {
    service_account = google_service_account.worker.email
    timeout         = "600s"
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = "${local.worker_image_base}/worker-alertes:${var.worker_image_tag}"
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.dataset_id
      }
      env {
        name  = "GCS_SIGNALS_BUCKET"
        value = google_storage_bucket.signals.name
      }
      env {
        name  = "GCS_ARTIFACTS_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
    }
  }
}

output "worker_service_account" {
  value       = google_service_account.worker.email
  description = "Compte de service utilisé par les workers Cloud Run"
}

output "artifact_registry_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
  description = "URL de base pour docker push"
}
