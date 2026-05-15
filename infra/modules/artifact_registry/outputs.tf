output "repository_id" {
  description = "Repository ID."
  value       = google_artifact_registry_repository.docker.repository_id
}

output "name" {
  description = "Fully qualified repository name (projects/.../locations/.../repositories/...)."
  value       = google_artifact_registry_repository.docker.name
}

output "docker_registry_url" {
  description = "Docker registry URL prefix (use as <url>/IMAGE:TAG)."
  value       = "${var.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}
