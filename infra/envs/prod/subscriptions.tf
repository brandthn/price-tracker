# push ticket-uploaded -> worker-ocr-vlm-scratch /push (tier-1), DLQ apres 5 echecs
resource "google_pubsub_subscription" "ticket_uploaded_ocr_push" {
  project = var.project_id
  name    = "ticket-uploaded-ocr-push"
  topic   = module.pubsub.topics["ticket-uploaded"].name

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
    dead_letter_topic     = module.pubsub.topics["ticket-uploaded-dlq"].id
    max_delivery_attempts = 5
  }

  labels = merge(var.labels, { component = "ocr-tier1-dispatch" })

  depends_on = [
    google_service_account_iam_member.pubsub_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}

# pubsub agent: subscriber (forward DLQ) + publisher (topic DLQ)
resource "google_pubsub_subscription_iam_member" "pubsub_agent_dlq_forwarder" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ticket_uploaded_ocr_push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

resource "google_pubsub_topic_iam_member" "pubsub_agent_dlq_publisher" {
  project = var.project_id
  topic   = module.pubsub.topics["ticket-uploaded-dlq"].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

# pull d'inspection sur le DLQ (accumulation jusqu'a replay/drop manuel)
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

# feedback loop: ocr-retry -> worker-ocr-llm /push (tier-2)
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

# backends ocr: un topic -> une push sub vers le worker /push

# paddle
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

# moondream
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

# scratch
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
