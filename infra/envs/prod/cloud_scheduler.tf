# crons workers batch : ingestion 03h, off 04h, indices 05h, alertes 07h (UTC), OIDC worker-sa
module "cloud_scheduler_jobs" {
  source = "../../modules/cloud_scheduler"

  project_id = var.project_id
  region     = var.region

  jobs = {
    "${var.name_prefix}-trigger-ingestion" = {
      schedule                   = "0 3 * * *"
      target_url                 = module.run_worker_ingestion.uri
      target_path                = "/run"
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "pull snapshot HF open-prices -> BQ silver."
    }
    "${var.name_prefix}-trigger-off" = {
      schedule                   = "0 4 * * *"
      target_url                 = module.run_worker_off.uri
      target_path                = "/run"
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "enrichissement EAN OFF + embeddings vertex."
    }
    "${var.name_prefix}-trigger-indices" = {
      schedule                   = "0 5 * * *"
      target_url                 = module.run_worker_indices.uri
      target_path                = "/run"
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "recalcul 4 tables BQ gold."
    }
    "${var.name_prefix}-trigger-alertes" = {
      schedule                   = "0 7 * * *"
      target_url                 = module.run_worker_alertes.uri
      target_path                = "/run"
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "agregation BQ gold -> rapport json GCS bronze/alerts/."
    }
  }

  depends_on = [
    google_service_account_iam_member.scheduler_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}


