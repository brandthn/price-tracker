# Repo Docker centralisé pour le backend et les workers.
# - Lecture : backend-sa, worker-sa (pull au démarrage Cloud Run)
# - Écriture : gh-actions-sa (push depuis CI, Phase 3)
module "artifact_registry" {
  source = "../../modules/artifact_registry"

  project_id    = var.project_id
  location      = var.region
  repository_id = "${var.name_prefix}-docker"
  labels        = merge(var.labels, { component = "artifact-registry" })

  readers = [local.backend_sa, local.worker_sa, local.frontend_sa]
  writers = [local.gh_actions_sa]
}
