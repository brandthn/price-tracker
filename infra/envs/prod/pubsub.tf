# Topics Pub/Sub — bus d'événements asynchrones.
# `ticket-uploaded` est alimenté directement par GCS via une Pub/Sub
# notification sur le bucket bronze (cf. notifications.tf) — pas d'Eventarc :
# le filtre `object_name_prefix` natif fait le job et économise une couche.
module "pubsub" {
  source = "../../modules/pubsub"

  project_id = var.project_id
  labels     = merge(var.labels, { component = "pubsub" })

  topics = {
    "ticket-uploaded" = {
      message_retention_duration = "604800s" # 7 jours (max Pub/Sub standard)
      # Le worker OCR consommera ce topic via une push subscription en Phase 8.
      # On donne déjà subscriber au worker-sa pour qu'il puisse créer / lire
      # la subscription dès qu'elle existera.
      subscribers = [local.worker_sa]
    }
  }
}
