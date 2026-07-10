# Topics Pub/Sub dédiés aux 6 workers OCR « un backend = un worker ».
#
# Un topic (+ son DLQ) par backend : publier sur `ocr-paddle` exerce le worker
# Paddle, sur `ocr-vlm-groq` le worker Groq, etc. Comparer deux backends = poster
# le même ticket_id sur deux topics.
#
# Pourquoi une SECONDE instanciation du module plutôt que des clés en plus dans
# `module.pubsub` (pubsub.tf) ? Ajouter des clés à sa map `topics` modifierait un
# fichier partagé et ferait passer les topics existants dans le même plan. Le
# module ne crée que des ressources par-topic (topic + IAM bindings), il est donc
# sûr de l'instancier deux fois. Les routages `ticket-uploaded` et `ocr-retry`
# restent strictement intacts.
module "pubsub_ocr_backends" {
  source = "../../modules/pubsub"

  project_id = var.project_id
  labels     = merge(var.labels, { component = "pubsub-ocr-backends" })

  topics = {
    # backend-sa publie le ticket_id ; worker-sa consomme via push subscription.
    "ocr-paddle" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-paddle-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }

    "ocr-ppocrv4" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-ppocrv4-dlq" = {
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

    "ocr-vlm-groq" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-vlm-groq-dlq" = {
      message_retention_duration = "604800s"
      subscribers                = [local.worker_sa]
    }

    "ocr-vlm-receipt" = {
      message_retention_duration = "604800s"
      publishers                 = [local.backend_sa]
      subscribers                = [local.worker_sa]
    }
    "ocr-vlm-receipt-dlq" = {
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
