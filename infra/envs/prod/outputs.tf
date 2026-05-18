output "tf_state_bucket" {
  description = "Name of the Terraform state bucket (managed via import)."
  value       = google_storage_bucket.tf_state.name
}

output "service_accounts" {
  description = "Map of service accounts (role => email/account_id/member)."
  value       = module.iam.service_accounts
}

output "terraform_sa_email" {
  description = "Email of the Terraform runner SA (used for impersonation)."
  value       = module.iam.emails["terraform"]
}

# --- Phase 2 -----------------------------------------------------------------

output "buckets" {
  description = "Data lake buckets (bronze, silver, models)."
  value = {
    bronze = module.bucket_bronze.name
    silver = module.bucket_silver.name
    models = module.bucket_models.name
  }
}

output "network" {
  description = "VPC and subnet identifiers. Cloud Run will attach to `subnet` via Direct VPC egress (Phase 5)."
  value = {
    vpc_self_link = module.network.vpc_self_link
    subnet_id     = module.network.subnet_id
    subnet_name   = module.network.subnet_name
  }
}

output "artifact_registry_url" {
  description = "Docker registry URL prefix (use as <url>/IMAGE:TAG)."
  value       = module.artifact_registry.docker_registry_url
}

output "secrets" {
  description = "Map of secret_id => resource ID."
  value       = module.secrets.secret_ids
}

# --- Phase 4 -----------------------------------------------------------------

output "cloud_sql" {
  description = "Cloud SQL instance — connection_name (project:region:instance) + private IP + db name."
  value = {
    instance_name   = module.cloud_sql_main.instance_name
    connection_name = module.cloud_sql_main.connection_name
    private_ip      = module.cloud_sql_main.private_ip_address
    db_name         = module.cloud_sql_main.db_name
    db_user         = module.cloud_sql_main.db_user
  }
}

output "bigquery_datasets" {
  description = "BigQuery datasets (project.dataset_id)."
  value       = { for k, v in module.bigquery.datasets : k => v.qualified }
}

output "pubsub_topics" {
  description = "Pub/Sub topics created."
  value       = module.pubsub.topic_ids
}

output "gcs_notification_ticket_uploaded" {
  description = "GCS→Pub/Sub notification ID for ticket uploads."
  value       = google_storage_notification.ticket_uploaded.id
}

# --- Phase 5 -----------------------------------------------------------------

output "cloud_run_services" {
  description = "Cloud Run services and their auto-generated HTTPS URIs."
  value = {
    backend          = { name = module.run_backend.name, uri = module.run_backend.uri }
    worker-ocr       = { name = module.run_worker_ocr.name, uri = module.run_worker_ocr.uri }
    worker-ingestion = { name = module.run_worker_ingestion.name, uri = module.run_worker_ingestion.uri }
    worker-off       = { name = module.run_worker_off.name, uri = module.run_worker_off.uri }
    worker-indices   = { name = module.run_worker_indices.name, uri = module.run_worker_indices.uri }
    worker-alertes   = { name = module.run_worker_alertes.name, uri = module.run_worker_alertes.uri }
  }
}

output "cloud_scheduler_jobs" {
  description = "Cloud Scheduler job IDs (cron triggers for batch workers)."
  value       = module.cloud_scheduler_jobs.job_ids
}

output "pubsub_subscriptions" {
  description = "Pub/Sub subscriptions wired in Phase 5."
  value = {
    ocr_push       = google_pubsub_subscription.ticket_uploaded_ocr_push.id
    dlq_inspection = google_pubsub_subscription.ticket_uploaded_dlq_inspection.id
  }
}

output "service_agents" {
  description = "Google-managed service agents materialized in Phase 5 (emails)."
  value = {
    cloudscheduler = google_project_service_identity.cloudscheduler.email
    pubsub         = google_project_service_identity.pubsub.email
  }
}
