# Subscriptions Pub/Sub des 6 workers OCR « un backend = un worker ».
#
# Clone exact des semantics de `ocr_retry_worker_push` (subscriptions.tf) :
#   - push vers ${service.uri}/push, token OIDC minté pour worker-sa
#   - ack_deadline 600s (> timeout Cloud Run 540s)
#   - retry backoff 10s → 600s, bascule DLQ après 5 tentatives
#   - une pull subscription d'inspection par DLQ
#
# Un `for_each` sur une map locale évite 6× ~60 lignes dupliquées. Fichier
# additif : aucune ressource de subscriptions.tf n'est modifiée.

locals {
  ocr_backend_push = {
    paddle = {
      uri   = module.run_worker_ocr_paddle.uri
      topic = "ocr-paddle"
    }
    ppocrv4 = {
      uri   = module.run_worker_ocr_ppocrv4.uri
      topic = "ocr-ppocrv4"
    }
    vlm_moondream = {
      uri   = module.run_worker_ocr_vlm_moondream.uri
      topic = "ocr-vlm-moondream"
    }
    vlm_groq = {
      uri   = module.run_worker_ocr_vlm_groq.uri
      topic = "ocr-vlm-groq"
    }
    vlm_receipt = {
      uri   = module.run_worker_ocr_vlm_receipt.uri
      topic = "ocr-vlm-receipt"
    }
    vlm_scratch = {
      uri   = module.run_worker_ocr_vlm_scratch.uri
      topic = "ocr-vlm-scratch"
    }
  }
}

# --- 1) Push subscriptions : <topic> → worker /push ------------------------
resource "google_pubsub_subscription" "ocr_backend_push" {
  for_each = local.ocr_backend_push

  project = var.project_id
  name    = "${each.value.topic}-push"
  topic   = module.pubsub_ocr_backends.topics[each.value.topic].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  push_config {
    push_endpoint = "${each.value.uri}/push"

    oidc_token {
      service_account_email = module.iam.emails["worker"]
      audience              = each.value.uri
    }

    attributes = {
      x-goog-version = "v1"
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = module.pubsub_ocr_backends.topics["${each.value.topic}-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "worker-${each.value.topic}" })

  # Ordre : Pub/Sub valide le push_config au create et renvoie PERMISSION_DENIED
  # si le service agent n'a pas TokenCreator sur worker-sa, ou si worker-sa n'a
  # pas run.invoker sur le service cible.
  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.ocr_backend_worker_sa_invoker,
  ]
}

# --- 2) IAM du service agent Pub/Sub pour la bascule DLQ -------------------
# subscriber sur la sub principale (lire le message à forwarder) + publisher sur
# le topic DLQ. Sans ça, la bascule échoue silencieusement et les messages
# bouclent. Bindings posés hors module pubsub : l'email du service agent n'existe
# qu'après création de la google_project_service_identity.
resource "google_pubsub_subscription_iam_member" "ocr_backend_dlq_forwarder" {
  for_each = local.ocr_backend_push

  project      = var.project_id
  subscription = google_pubsub_subscription.ocr_backend_push[each.key].name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

resource "google_pubsub_topic_iam_member" "ocr_backend_dlq_publisher" {
  for_each = local.ocr_backend_push

  project = var.project_id
  topic   = module.pubsub_ocr_backends.topics["${each.value.topic}-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

# --- 3) Pull subscriptions d'inspection sur les DLQ -----------------------
# Pas de push : les messages empoisonnés s'accumulent jusqu'à inspection
# manuelle (console GCP ou `gcloud pubsub subscriptions pull`).
resource "google_pubsub_subscription" "ocr_backend_dlq_inspection" {
  for_each = local.ocr_backend_push

  project = var.project_id
  name    = "${each.value.topic}-dlq-inspection"
  topic   = module.pubsub_ocr_backends.topics["${each.value.topic}-dlq"].name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  labels = merge(var.labels, { component = "worker-${each.value.topic}-dlq" })
}
