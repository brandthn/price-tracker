locals {
  # Flatten (dataset_id, role, member) tuples for dataset-level IAM bindings.
  iam_bindings = merge([
    for ds_id, spec in var.datasets : merge(
      { for m in spec.editors : "${ds_id}:editor:${m}" => { dataset_id = ds_id, role = "roles/bigquery.dataEditor", member = m } },
      { for m in spec.viewers : "${ds_id}:viewer:${m}" => { dataset_id = ds_id, role = "roles/bigquery.dataViewer", member = m } },
      { for m in spec.owners : "${ds_id}:owner:${m}" => { dataset_id = ds_id, role = "roles/bigquery.dataOwner", member = m } },
    )
  ]...)
}

resource "google_bigquery_dataset" "this" {
  for_each = var.datasets

  project                     = var.project_id
  dataset_id                  = each.key
  location                    = var.location
  description                 = each.value.description
  default_table_expiration_ms = each.value.default_table_expiration_ms
  labels                      = var.labels
}

resource "google_bigquery_dataset_iam_member" "binding" {
  for_each = local.iam_bindings

  project    = var.project_id
  dataset_id = google_bigquery_dataset.this[each.value.dataset_id].dataset_id
  role       = each.value.role
  member     = each.value.member
}
