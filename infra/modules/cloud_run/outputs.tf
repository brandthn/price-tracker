output "name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.this.name
}

output "id" {
  description = "Cloud Run service fully qualified ID (projects/.../locations/.../services/...)."
  value       = google_cloud_run_v2_service.this.id
}

output "location" {
  description = "Region of the service."
  value       = google_cloud_run_v2_service.this.location
}

output "uri" {
  description = "Public HTTPS URL of the service. Use as Cloud Scheduler target URL and as OIDC audience."
  value       = google_cloud_run_v2_service.this.uri
}

output "service_account_email" {
  description = "Runtime SA attached to the service (echo back for convenience)."
  value       = var.service_account_email
}
