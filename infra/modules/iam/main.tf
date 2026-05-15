locals {
  # Flatten map<role, list<project_role>> -> list of {role, project_role} for IAM bindings.
  role_bindings = flatten([
    for role_key, spec in var.service_accounts : [
      for project_role in spec.project_roles : {
        role_key     = role_key
        project_role = project_role
      }
    ]
  ])
}

resource "google_service_account" "this" {
  for_each = var.service_accounts

  project      = var.project_id
  account_id   = "${var.name_prefix}-${each.key}-sa"
  display_name = each.value.display_name
  description  = each.value.description
}

resource "google_project_iam_member" "this" {
  for_each = {
    for binding in local.role_bindings :
    "${binding.role_key}:${binding.project_role}" => binding
  }

  project = var.project_id
  role    = each.value.project_role
  member  = "serviceAccount:${google_service_account.this[each.value.role_key].email}"
}
