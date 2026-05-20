output "bucket_bronze" {
  value = google_storage_bucket.bronze.name
}

output "bucket_signals" {
  value = google_storage_bucket.signals.name
}

output "bucket_artifacts" {
  value = google_storage_bucket.artifacts.name
}

output "bigquery_dataset" {
  value = google_bigquery_dataset.dw.dataset_id
}
