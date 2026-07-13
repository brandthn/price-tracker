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
    # uri = url + path ; audience = url seule (aud OIDC sans path)
    uri  = "${each.value.target_url}${each.value.target_path}"
    body = each.value.body_base64

    oidc_token {
      service_account_email = each.value.oidc_service_account_email
      audience              = each.value.target_url
    }
  }
}
