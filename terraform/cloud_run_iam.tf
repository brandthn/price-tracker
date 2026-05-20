# Autorise le compte « worker » à invoquer ses propres services (OIDC depuis Cloud Scheduler).

resource "google_cloud_run_v2_service_iam_member" "ingestion_invoker" {
  count    = var.create_cloud_run_services ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ingestion[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_cloud_run_v2_service_iam_member" "off_invoker" {
  count    = var.create_cloud_run_services ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.off[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_cloud_run_v2_service_iam_member" "indices_invoker" {
  count    = var.create_cloud_run_services ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.indices[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_cloud_run_v2_service_iam_member" "alertes_invoker" {
  count    = var.create_cloud_run_services ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.alertes[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}
