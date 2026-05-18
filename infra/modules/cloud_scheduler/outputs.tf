output "job_ids" {
  description = "Map of job_name => fully qualified job ID."
  value       = { for k, j in google_cloud_scheduler_job.this : k => j.id }
}

output "job_names" {
  description = "Map of job_name => short name."
  value       = { for k, j in google_cloud_scheduler_job.this : k => j.name }
}
