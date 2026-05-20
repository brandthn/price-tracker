resource "google_bigquery_dataset" "dw" {
  dataset_id                 = var.dataset_id
  location                   = var.bq_location
  delete_contents_on_destroy = false
}

# Les tables Silver / Gold sont créées ou mises à jour par les workers (Python + SQL).
# Le dataset ci-dessus suffit pour un premier `terraform apply`.
