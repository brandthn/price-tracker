resource "google_artifact_registry_repository" "docker" {
  project       = var.project_id
  location      = var.location
  repository_id = var.repository_id
  description   = var.description
  format        = "DOCKER"
  labels        = var.labels

  dynamic "cleanup_policies" {
    for_each = var.cleanup_keep_count > 0 ? [1] : []
    content {
      id     = "keep-recent-versions"
      action = "KEEP"
      most_recent_versions {
        keep_count = var.cleanup_keep_count
      }
    }
  }
}

resource "google_artifact_registry_repository_iam_member" "reader" {
  for_each = toset(var.readers)

  project    = var.project_id
  location   = var.location
  repository = google_artifact_registry_repository.docker.repository_id
  role       = "roles/artifactregistry.reader"
  member     = each.value
}

resource "google_artifact_registry_repository_iam_member" "writer" {
  for_each = toset(var.writers)

  project    = var.project_id
  location   = var.location
  repository = google_artifact_registry_repository.docker.repository_id
  role       = "roles/artifactregistry.writer"
  member     = each.value
}
