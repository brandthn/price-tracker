# Topics Pub/Sub — bus d'événements asynchrones.
# `ticket-uploaded` est alimenté directement par GCS via une Pub/Sub
# notification sur le bucket bronze (cf. notifications.tf) — pas d'Eventarc :
# le filtre `object_name_prefix` natif fait le job et économise une couche.
#
# `ticket-uploaded-dlq` (Phase 5) reçoit les messages que worker-ocr n'a pas
# réussi à traiter après `max_delivery_attempts` tentatives. Pattern standard
# Pub/Sub : isoler les empoisonnés pour inspection humaine sans bloquer le flux.
module "pubsub" {
  source = "../../modules/pubsub"

  project_id = var.project_id
  labels     = merge(var.labels, { component = "pubsub" })

  topics = {
    "ticket-uploaded" = {
      message_retention_duration = "604800s" # 7 jours (max Pub/Sub standard)
      # Le worker OCR consomme ce topic via une push subscription (cf. subscriptions.tf).
      subscribers = [local.worker_sa]
    }
    "ticket-uploaded-dlq" = {
      message_retention_duration = "604800s"
      # Binding `publishers` (Pub/Sub service agent) défini directement dans
      # subscriptions.tf via google_pubsub_topic_iam_member — son email
      # provient d'une ressource créée au même apply (known after apply), donc
      # impossible de le passer en clé d'un for_each de module.
      # worker-sa peut consommer le DLQ (replay manuel ou inspection).
      subscribers = [local.worker_sa]
    }
  }
}
