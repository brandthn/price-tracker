output "instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.this.name
}

output "connection_name" {
  description = "Cloud SQL connection name (project:region:instance) — used by Cloud SQL Auth Proxy."
  value       = google_sql_database_instance.this.connection_name
}

output "private_ip_address" {
  description = "Instance private IP within the VPC."
  value       = google_sql_database_instance.this.private_ip_address
}

output "db_name" {
  description = "Application database name."
  value       = google_sql_database.app.name
}

output "db_user" {
  description = "Application Postgres user name."
  value       = google_sql_user.app.name
}

output "password_secret_version" {
  description = "Resource ID of the password Secret Manager version (vN)."
  value       = google_secret_manager_secret_version.app_password.id
  sensitive   = true
}
