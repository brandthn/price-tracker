# notif GCS -> topic ticket-uploaded (pas d'Eventarc). le data source materialise
# le service agent GCS (ne pas hardcoder son email).
data "google_storage_project_service_account" "gcs" {
  project = var.project_id
}

locals {
  gcs_service_agent = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

# gcs agent publisher sur ticket-uploaded (requis avant la notification)
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

  depends_on = [google_pubsub_topic_iam_member.gcs_to_ticket_uploaded]
}
