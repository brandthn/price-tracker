# repo docker : readers backend/worker/frontend, writer gh-actions
module "artifact_registry" {
  source = "../../modules/artifact_registry"

  project_id    = var.project_id
  location      = var.region
  repository_id = "${var.name_prefix}-docker"
  labels        = merge(var.labels, { component = "artifact-registry" })

  readers = [local.backend_sa, local.worker_sa, local.frontend_sa]
  writers = [local.gh_actions_sa]
}
