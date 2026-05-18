# Service agents Google-managed nécessaires en Phase 5.
#
# Les service agents (`service-<project_number>@<gcp-sa-XXX>.iam.gserviceaccount.com`)
# sont créés *paresseusement* la première fois qu'on les sollicite. Avant cela,
# leur email existe « en théorie » mais leur SA n'est pas matérialisée dans le
# projet → toute tentative de binding IAM échoue avec un 400 « does not exist ».
#
# `google_project_service_identity` (provider google-beta) force la création et
# expose l'email — c'est l'équivalent de `gcloud beta services identity create`.
# ⚠️ Ne JAMAIS hardcoder ces emails dans Terraform (cf. memory feedback-gcp-service-agents-lazy).

# Service agent Cloud Scheduler — utilisé pour minter le token OIDC qui sera
# envoyé en Bearer aux Cloud Run cibles (workers cron).
resource "google_project_service_identity" "cloudscheduler" {
  provider = google-beta
  project  = var.project_id
  service  = "cloudscheduler.googleapis.com"
}

# Service agent Pub/Sub — utilisé pour minter le token OIDC envoyé par la push
# subscription vers le worker-ocr, et pour publier dans la dead-letter topic.
resource "google_project_service_identity" "pubsub" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"
}

locals {
  cloudscheduler_agent_member = "serviceAccount:${google_project_service_identity.cloudscheduler.email}"
  pubsub_agent_member         = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

# Les service agents Scheduler / Pub/Sub doivent pouvoir « impersonner »
# worker-sa pour générer le token OIDC dont l'`iss` claim désigne worker-sa.
# Sans ce binding, Scheduler/Pub/Sub n'ont pas le droit de mint un token au
# nom de worker-sa → les jobs et les push échouent avec PERMISSION_DENIED.
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

# Le binding qui autorise le service agent Pub/Sub à publier sur le DLQ topic
# est défini dans subscriptions.tf (`pubsub_agent_dlq_publisher`), au plus
# près du wiring DLQ qu'il déverrouille.
