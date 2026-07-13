# service agents lazy-created via google_project_service_identity (ne pas hardcoder les emails)

resource "google_project_service_identity" "cloudscheduler" {
  provider = google-beta
  project  = var.project_id
  service  = "cloudscheduler.googleapis.com"
}

resource "google_project_service_identity" "pubsub" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"
}

locals {
  cloudscheduler_agent_member = "serviceAccount:${google_project_service_identity.cloudscheduler.email}"
  pubsub_agent_member         = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

# scheduler/pubsub agents doivent pouvoir minter un token OIDC au nom de worker-sa
resource "google_service_account_iam_member" "scheduler_token_creator_on_worker" {
  service_account_id = module.iam.service_accounts["worker"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.cloudscheduler_agent_member
}

resource "google_service_account_iam_member" "pubsub_token_creator_on_worker" {
  service_account_id = module.iam.service_accounts["worker"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent_member
}
