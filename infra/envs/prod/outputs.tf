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
