locals {
  # Flatten (secret_id, accessor) for IAM bindings.
  accessor_bindings = flatten([
    for secret_id, spec in var.secrets : [
      for accessor in spec.accessors : {
        secret_id = secret_id
        member    = accessor
      }
    ]
  ])
}

resource "google_secret_manager_secret" "this" {
  for_each = var.secrets

  project   = var.project_id
  secret_id = each.key
  labels    = var.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = {
    for binding in local.accessor_bindings :
    "${binding.secret_id}:${binding.member}" => binding
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.value.secret_id].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}
