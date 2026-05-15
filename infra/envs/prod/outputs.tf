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
