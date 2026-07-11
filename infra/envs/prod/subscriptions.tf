# Pub/Sub subscriptions — Phase 5.
#
# Deux subscriptions :
#   1. Push   : `ticket-uploaded` → `prt-prod-worker-ocr` (déclenche le pipeline OCR)
#   2. Pull   : `ticket-uploaded-dlq` (inspection / replay manuel des messages empoisonnés)
#
# Le DLQ wiring vit côté subscription principale (`dead_letter_policy`), pas côté topic.

# --- 1) Push subscription : ticket-uploaded → worker-ocr -------------------
#
# OIDC auth : Cloud Run vérifie le token signé par Google contre :
#   - aud  == URL exacte du service `prt-prod-worker-ocr` (audience)
#   - iss  == worker-sa (qui a `roles/run.invoker` via cloud_run.tf)
#
# DLQ : après 5 échecs (5xx ou non-ack dans ack_deadline), Pub/Sub bascule le
# message vers `ticket-uploaded-dlq`. Le retry policy fait un backoff
# exponentiel entre 10s et 600s entre deux tentatives.
#
# `ack_deadline_seconds=600` : laisse 10 min au worker pour traiter une image
# avant de re-livrer. À ajuster en Phase 8 selon le P95 mesuré de l'OCR.
resource "google_pubsub_subscription" "ticket_uploaded_ocr_push" {
  project = var.project_id
  name    = "ticket-uploaded-ocr-push"
  topic   = module.pubsub.topics["ticket-uploaded"].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  push_config {
    # Convention : le worker OCR expose son handler sur /push (cf. plan-01
    # Phase 8). En Phase 5 l'image hello répond 200 sur n'importe quel path.
    push_endpoint = "${module.run_worker_ocr.uri}/push"

    oidc_token {
      service_account_email = module.iam.emails["worker"]
      audience              = module.run_worker_ocr.uri
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
    dead_letter_topic     = module.pubsub.topics["ticket-uploaded-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "worker-ocr" })

  # Ordre : la sub principale ne peut pas être créée tant que :
  #   - le service agent Pub/Sub n'a pas TokenCreator sur worker-sa
  #   - worker-sa n'a pas run.invoker sur worker-ocr
  # Sinon Pub/Sub valide le push_config au create et renvoie PERMISSION_DENIED.
  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}

# Pub/Sub service agent a besoin de `roles/pubsub.subscriber` sur la sub
# principale pour pouvoir « lire » le message à forwarder vers le DLQ.
# Sans ça, le bascule DLQ échoue silencieusement et les messages bouclent.
resource "google_pubsub_subscription_iam_member" "pubsub_agent_dlq_forwarder" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ticket_uploaded_ocr_push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

# Pub/Sub service agent doit pouvoir publier dans le DLQ topic. Binding posé
# hors module pubsub car son email n'existe qu'après création de la
# google_project_service_identity → for_each du module rejette une clé inconnue.
resource "google_pubsub_topic_iam_member" "pubsub_agent_dlq_publisher" {
  project = var.project_id
  topic   = module.pubsub.topics["ticket-uploaded-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

# --- 2) Pull subscription d'inspection sur le DLQ --------------------------
#
# Pas de push : on veut que les messages s'accumulent jusqu'à inspection
# manuelle (console GCP ou `gcloud pubsub subscriptions pull`).
# 7 jours de rétention = fenêtre standard pour décider replay ou drop.
resource "google_pubsub_subscription" "ticket_uploaded_dlq_inspection" {
  project = var.project_id
  name    = "ticket-uploaded-dlq-inspection"
  topic   = module.pubsub.topics["ticket-uploaded-dlq"].name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  labels = merge(var.labels, { component = "worker-ocr-dlq" })
}

# --- 3) Boucle de feedback : ocr-retry → worker-ocr-llm /push --------------
#
# Déclenchée par un 👎 utilisateur (le backend publie {ticket_id} sur le topic
# `ocr-retry`). Le message est poussé vers le **second worker indépendant**
# `worker-ocr-llm` (OCR tier-2). Même schéma OIDC/DLQ que la subscription OCR
# principale : le token est minté pour worker-sa (autorisé à invoquer
# worker-ocr-llm via `worker_sa_invoker`).
resource "google_pubsub_subscription" "ocr_retry_worker_push" {
  project = var.project_id
  name    = "ocr-retry-worker-push"
  topic   = module.pubsub.topics["ocr-retry"].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  push_config {
    push_endpoint = "${module.run_worker_ocr_llm.uri}/push"

    oidc_token {
      service_account_email = module.iam.emails["worker"]
      audience              = module.run_worker_ocr_llm.uri
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
    dead_letter_topic     = module.pubsub.topics["ocr-retry-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "worker-ocr-retry" })

  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}

# Pub/Sub service agent : subscriber sur la sub retry (bascule DLQ) + publisher
# sur le topic DLQ retry. Mêmes raisons que pour le DLQ OCR principal.
resource "google_pubsub_subscription_iam_member" "pubsub_agent_retry_dlq_forwarder" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ocr_retry_worker_push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

resource "google_pubsub_topic_iam_member" "pubsub_agent_retry_dlq_publisher" {
  project = var.project_id
  topic   = module.pubsub.topics["ocr-retry-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

resource "google_pubsub_subscription" "ocr_retry_dlq_inspection" {
  project = var.project_id
  name    = "ocr-retry-dlq-inspection"
  topic   = module.pubsub.topics["ocr-retry-dlq"].name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  labels = merge(var.labels, { component = "worker-ocr-retry-dlq" })
}

# --- 4) Backends OCR « un backend = un worker » ----------------------------
#
# Un backend = un topic → une push subscription vers son worker /push, même
# schéma OIDC/DLQ que la sub OCR principale. Le pipeline (scratch → moondream →
# ocr-retry) est piloté par le backend en publiant {ticket_id} sur le topic du
# tier voulu ; les workers ne s'appellent pas entre eux.

# 4a) Backend PaddleOCR
resource "google_pubsub_subscription" "ocr_paddle_worker_push" {
  project = var.project_id
  name    = "ocr-paddle-push"
  topic   = module.pubsub.topics["ocr-paddle"].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  push_config {
    push_endpoint = "${module.run_worker_ocr_paddle.uri}/push"

    oidc_token {
      service_account_email = module.iam.emails["worker"]
      audience              = module.run_worker_ocr_paddle.uri
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
    dead_letter_topic     = module.pubsub.topics["ocr-paddle-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "worker-ocr-paddle" })

  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}

resource "google_pubsub_subscription_iam_member" "pubsub_agent_paddle_dlq_forwarder" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ocr_paddle_worker_push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

resource "google_pubsub_topic_iam_member" "pubsub_agent_paddle_dlq_publisher" {
  project = var.project_id
  topic   = module.pubsub.topics["ocr-paddle-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

resource "google_pubsub_subscription" "ocr_paddle_dlq_inspection" {
  project = var.project_id
  name    = "ocr-paddle-dlq-inspection"
  topic   = module.pubsub.topics["ocr-paddle-dlq"].name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  labels = merge(var.labels, { component = "worker-ocr-paddle-dlq" })
}

# 4b) Backend VLM Moondream
resource "google_pubsub_subscription" "ocr_vlm_moondream_worker_push" {
  project = var.project_id
  name    = "ocr-vlm-moondream-push"
  topic   = module.pubsub.topics["ocr-vlm-moondream"].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  push_config {
    push_endpoint = "${module.run_worker_ocr_vlm_moondream.uri}/push"

    oidc_token {
      service_account_email = module.iam.emails["worker"]
      audience              = module.run_worker_ocr_vlm_moondream.uri
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
    dead_letter_topic     = module.pubsub.topics["ocr-vlm-moondream-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "worker-ocr-vlm-moondream" })

  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}

resource "google_pubsub_subscription_iam_member" "pubsub_agent_moondream_dlq_forwarder" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ocr_vlm_moondream_worker_push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

resource "google_pubsub_topic_iam_member" "pubsub_agent_moondream_dlq_publisher" {
  project = var.project_id
  topic   = module.pubsub.topics["ocr-vlm-moondream-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

resource "google_pubsub_subscription" "ocr_vlm_moondream_dlq_inspection" {
  project = var.project_id
  name    = "ocr-vlm-moondream-dlq-inspection"
  topic   = module.pubsub.topics["ocr-vlm-moondream-dlq"].name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  labels = merge(var.labels, { component = "worker-ocr-vlm-moondream-dlq" })
}

# 4c) Backend OCR-VLM from-scratch
resource "google_pubsub_subscription" "ocr_vlm_scratch_worker_push" {
  project = var.project_id
  name    = "ocr-vlm-scratch-push"
  topic   = module.pubsub.topics["ocr-vlm-scratch"].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  push_config {
    push_endpoint = "${module.run_worker_ocr_vlm_scratch.uri}/push"

    oidc_token {
      service_account_email = module.iam.emails["worker"]
      audience              = module.run_worker_ocr_vlm_scratch.uri
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
    dead_letter_topic     = module.pubsub.topics["ocr-vlm-scratch-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "worker-ocr-vlm-scratch" })

  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}

resource "google_pubsub_subscription_iam_member" "pubsub_agent_scratch_dlq_forwarder" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ocr_vlm_scratch_worker_push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

resource "google_pubsub_topic_iam_member" "pubsub_agent_scratch_dlq_publisher" {
  project = var.project_id
  topic   = module.pubsub.topics["ocr-vlm-scratch-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

resource "google_pubsub_subscription" "ocr_vlm_scratch_dlq_inspection" {
  project = var.project_id
  name    = "ocr-vlm-scratch-dlq-inspection"
  topic   = module.pubsub.topics["ocr-vlm-scratch-dlq"].name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_message_ordering    = false

  labels = merge(var.labels, { component = "worker-ocr-vlm-scratch-dlq" })
}
