resource "google_cloud_scheduler_job" "this" {
  for_each = var.jobs

  project     = var.project_id
  region      = var.region
  name        = each.key
  description = each.value.description
  schedule    = each.value.schedule
  time_zone   = each.value.time_zone
  paused      = each.value.paused

  retry_config {
    retry_count = each.value.retry_count
  }

  http_target {
    http_method = each.value.http_method
    uri         = each.value.target_url
    body        = each.value.body_base64

    oidc_token {
      service_account_email = each.value.oidc_service_account_email
      # OIDC audience MUST equal the root URL of the Cloud Run service for
      # signature verification to pass (Cloud Run checks aud claim against the
      # service URL). Stripping any path from target_url isn't needed when the
      # target already IS the root; we pass target_url as-is per Google docs.
      audience = each.value.target_url
    }
  }
}
