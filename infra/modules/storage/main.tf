resource "google_storage_bucket" "this" {
  name                        = var.name
  project                     = var.project_id
  location                    = var.location
  storage_class               = var.storage_class
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "lifecycle_rule" {
    for_each = var.lifecycle_rules
    content {
      action {
        type          = lifecycle_rule.value.action_type
        storage_class = lifecycle_rule.value.action_storage_class
      }
      condition {
        age                        = lifecycle_rule.value.age
        num_newer_versions         = lifecycle_rule.value.num_newer_versions
        days_since_noncurrent_time = lifecycle_rule.value.days_since_noncurrent_time
        with_state                 = lifecycle_rule.value.with_state
      }
    }
  }

  dynamic "cors" {
    for_each = var.cors
    content {
      origin          = cors.value.origin
      method          = cors.value.method
      response_header = cors.value.response_header
      max_age_seconds = cors.value.max_age_seconds
    }
  }

  labels = var.labels
}

resource "google_storage_bucket_iam_member" "object_admin" {
  for_each = toset(var.object_admins)
  bucket   = google_storage_bucket.this.name
  role     = "roles/storage.objectAdmin"
  member   = each.value
}

resource "google_storage_bucket_iam_member" "object_viewer" {
  for_each = toset(var.object_viewers)
  bucket   = google_storage_bucket.this.name
  role     = "roles/storage.objectViewer"
  member   = each.value
}

resource "google_storage_bucket_iam_member" "object_creator" {
  for_each = toset(var.object_creators)
  bucket   = google_storage_bucket.this.name
  role     = "roles/storage.objectCreator"
  member   = each.value
}
