output "vpc_id" {
  description = "VPC resource ID."
  value       = google_compute_network.vpc.id
}

output "vpc_self_link" {
  description = "VPC self link (used by Cloud SQL for private_network)."
  value       = google_compute_network.vpc.self_link
}

output "vpc_name" {
  description = "VPC name."
  value       = google_compute_network.vpc.name
}

output "subnet_id" {
  description = "Primary subnet ID. Cloud Run uses this via Direct VPC egress (Phase 5)."
  value       = google_compute_subnetwork.primary.id
}

output "subnet_self_link" {
  description = "Primary subnet self link."
  value       = google_compute_subnetwork.primary.self_link
}

output "subnet_name" {
  description = "Primary subnet name."
  value       = google_compute_subnetwork.primary.name
}

output "psa_connection" {
  description = "Service Networking connection (for explicit depends_on on Cloud SQL)."
  value       = google_service_networking_connection.psa.id
}
