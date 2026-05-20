# Cloud Scheduler — déclenche les services Cloud Run (HTTP authentifié OIDC).
# Actif uniquement si les services Run existent (`create_cloud_run_services = true`).

resource "google_cloud_scheduler_job" "ingestion" {
  count     = var.create_cloud_run_services ? 1 : 0
  name      = "open-prices-ingestion"
  region    = var.region
  schedule  = "0 3 * * *"
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.ingestion[0].uri
    oidc_token {
      service_account_email = google_service_account.worker.email
    }
  }

  depends_on = [google_cloud_run_v2_service.ingestion]
}

resource "google_cloud_scheduler_job" "off" {
  count     = var.create_cloud_run_services ? 1 : 0
  name      = "open-prices-off"
  region    = var.region
  schedule  = "0 4 * * *"
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.off[0].uri
    oidc_token {
      service_account_email = google_service_account.worker.email
    }
  }

  depends_on = [google_cloud_run_v2_service.off]
}

resource "google_cloud_scheduler_job" "indices" {
  count     = var.create_cloud_run_services ? 1 : 0
  name      = "open-prices-indices"
  region    = var.region
  schedule  = "0 5 * * *"
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.indices[0].uri
    oidc_token {
      service_account_email = google_service_account.worker.email
    }
  }

  depends_on = [google_cloud_run_v2_service.indices]
}

resource "google_cloud_scheduler_job" "alertes" {
  count     = var.create_cloud_run_services ? 1 : 0
  name      = "open-prices-alertes"
  region    = var.region
  schedule  = "0 7 * * *"
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.alertes[0].uri
    oidc_token {
      service_account_email = google_service_account.worker.email
    }
  }

  depends_on = [google_cloud_run_v2_service.alertes]
}
