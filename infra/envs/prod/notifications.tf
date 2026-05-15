# GCS → Pub/Sub notification : déclenche le pipeline OCR à chaque ticket uploadé.
#
# Pourquoi pas Eventarc ? Le plan initial prévoyait un trigger Eventarc, mais
# `google_storage_notification` est plus direct pour ce cas d'usage :
#   - 1 ressource au lieu de 3 (trigger + SA + binding)
#   - Filtre `object_name_prefix` natif (Eventarc ne le supporte pas)
#   - Pas de coût d'overhead (Eventarc facture les events qu'il route)
# Le worker OCR (Phase 8) consommera le topic `ticket-uploaded` via une push
# subscription Pub/Sub — fonctionnellement équivalent à un trigger Eventarc.

# Récupère l'email du GCS service agent ET le PROVISIONNE s'il n'existe pas
# encore (les service agents Google-managed sont créés paresseusement à la
# première opération qui les sollicite — pas à l'activation de l'API). L'appel
# API derrière ce data source (`storage.projects.getServiceAccount`) suffit à
# le matérialiser.
#
# Ne JAMAIS hardcoder l'email `service-{project_number}@gs-project-accounts.iam.gserviceaccount.com`
# avant ce data source : le binding IAM échouerait avec un 400 "does not exist".
data "google_storage_project_service_account" "gcs" {
  project = var.project_id
}

locals {
  gcs_service_agent = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

# Donner au GCS service agent le droit de publier dans le topic ticket-uploaded.
# REQUIS avant que google_storage_notification puisse être créé.
resource "google_pubsub_topic_iam_member" "gcs_to_ticket_uploaded" {
  project = var.project_id
  topic   = module.pubsub.topics["ticket-uploaded"].name
  role    = "roles/pubsub.publisher"
  member  = local.gcs_service_agent
}

resource "google_storage_notification" "ticket_uploaded" {
  bucket             = module.bucket_bronze.name
  payload_format     = "JSON_API_V1"
  topic              = module.pubsub.topics["ticket-uploaded"].id
  event_types        = ["OBJECT_FINALIZE"]
  object_name_prefix = "tickets/raw/"

  # Ne pas créer la notification avant que le service agent ait le rôle publisher.
  depends_on = [google_pubsub_topic_iam_member.gcs_to_ticket_uploaded]
}
