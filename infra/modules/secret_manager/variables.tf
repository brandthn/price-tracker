variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "labels" {
  description = "Common labels applied to every secret."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = <<-EOT
    Map of secret_id => spec. Creates the secret container (no version) and
    binds the listed accessors to `roles/secretmanager.secretAccessor` on it.
    The actual secret value is populated out-of-band (gcloud / console) or by
    a later module (e.g. Cloud SQL password generated in Phase 4).
  EOT
  type = map(object({
    accessors      = list(string)
    description    = optional(string, "")
    auto_replicate = optional(bool, true)
  }))
}
