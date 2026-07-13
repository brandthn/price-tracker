# topics pub/sub. ticket-uploaded alimente par notif GCS (notifications.tf),
# *-dlq pour les messages non traites apres max_delivery_attempts.
module "pubsub" {
  source = "../../modules/pubsub"

  project_id = var.project_id
  labels     = merge(var.labels, { component = "pubsub" })

  topics = {
    "ticket-uploaded" = {
      message_retention_duration = "604800s" # 7 jours
      subscribers                = [local.worker_sa]
    }
    "ticket-uploaded-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }

    # feedback loop: backend publie ticket_id -> re-ocr tier-2
    "ocr-retry" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-retry-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }

    # un topic (+dlq) par moteur ocr
    "ocr-paddle" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-paddle-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }
    "ocr-vlm-moondream" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-vlm-moondream-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }
    "ocr-vlm-scratch" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-vlm-scratch-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }
  }
}
