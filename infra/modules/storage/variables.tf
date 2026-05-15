variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name" {
  description = "Bucket name (globally unique)."
  type        = string
}

variable "location" {
  description = "Bucket location (EU multi-region, or single region)."
  type        = string
  default     = "EU"
}

variable "storage_class" {
  description = "Default storage class."
  type        = string
  default     = "STANDARD"
}

variable "force_destroy" {
  description = "Allow Terraform to destroy a non-empty bucket. Keep `false` outside tests."
  type        = bool
  default     = false
}

variable "versioning_enabled" {
  description = "Enable object versioning."
  type        = bool
  default     = false
}

variable "lifecycle_rules" {
  description = <<-EOT
    List of lifecycle rules. Each item is a Terraform lifecycle_rule block.
    Pass an empty list to disable lifecycle.
  EOT
  type = list(object({
    action_type                = string
    action_storage_class       = optional(string)
    age                        = optional(number)
    num_newer_versions         = optional(number)
    days_since_noncurrent_time = optional(number)
    with_state                 = optional(string)
  }))
  default = []
}

variable "labels" {
  description = "Labels applied to the bucket."
  type        = map(string)
  default     = {}
}

variable "object_admins" {
  description = "List of SA members (`serviceAccount:email`) granted `roles/storage.objectAdmin` on the bucket."
  type        = list(string)
  default     = []
}

variable "object_viewers" {
  description = "List of SA members granted `roles/storage.objectViewer` on the bucket."
  type        = list(string)
  default     = []
}

variable "object_creators" {
  description = "List of SA members granted `roles/storage.objectCreator` on the bucket (write-only, no read)."
  type        = list(string)
  default     = []
}
