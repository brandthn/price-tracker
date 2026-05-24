variable "project_id" {
  description = "GCP project ID hosting the Cloud Scheduler jobs."
  type        = string
}

variable "region" {
  description = "Cloud Scheduler region. Must match the Cloud Run target region (Scheduler is regional)."
  type        = string
}

variable "jobs" {
  description = <<-EOT
    Map of job_name => job spec.
      schedule                  : cron string (e.g. "0 3 * * *")
      target_url                : full HTTPS URL of the Cloud Run service (root). Used as OIDC audience (Cloud Run signature check requires audience = service root URL).
      target_path               : optional path appended to target_url for the actual HTTP request (default ""). Example: "/run". Kept separate from audience so OIDC stays valid.
      oidc_service_account_email: SA whose identity is used to mint the OIDC token; must have run.invoker on the target
      description               : human description
      time_zone                 : TZ database name (default "Etc/UTC")
      http_method               : POST (default) / GET / PUT / DELETE
      body_base64               : optional request body, already base64-encoded (Terraform-friendly)
      paused                    : start the job paused (true) or running (false, default)
      retry_count               : retry attempts on non-2xx (default 3)
  EOT
  type = map(object({
    schedule                   = string
    target_url                 = string
    target_path                = optional(string, "")
    oidc_service_account_email = string
    description                = optional(string, "")
    time_zone                  = optional(string, "Etc/UTC")
    http_method                = optional(string, "POST")
    body_base64                = optional(string, null)
    paused                     = optional(bool, false)
    retry_count                = optional(number, 3)
  }))
}
