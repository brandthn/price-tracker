locals {
  publisher_bindings = merge([
    for name, spec in var.topics : {
      for m in spec.publishers : "${name}:pub:${m}" => { topic = name, member = m }
    }
  ]...)

  subscriber_bindings = merge([
    for name, spec in var.topics : {
      for m in spec.subscribers : "${name}:sub:${m}" => { topic = name, member = m }
    }
  ]...)
}

resource "google_pubsub_topic" "this" {
  for_each = var.topics

  name                       = each.key
  project                    = var.project_id
  message_retention_duration = each.value.message_retention_duration
  labels                     = var.labels
}

resource "google_pubsub_topic_iam_member" "publisher" {
  for_each = local.publisher_bindings

  project = var.project_id
  topic   = google_pubsub_topic.this[each.value.topic].name
  role    = "roles/pubsub.publisher"
  member  = each.value.member
}

resource "google_pubsub_topic_iam_member" "subscriber" {
  for_each = local.subscriber_bindings

  project = var.project_id
  topic   = google_pubsub_topic.this[each.value.topic].name
  role    = "roles/pubsub.subscriber"
  member  = each.value.member
}
