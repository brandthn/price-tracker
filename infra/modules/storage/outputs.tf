output "name" {
  description = "Bucket name."
  value       = google_storage_bucket.this.name
}

output "url" {
  description = "Bucket gs:// URL."
  value       = google_storage_bucket.this.url
}

output "id" {
  description = "Bucket resource ID."
  value       = google_storage_bucket.this.id
}
