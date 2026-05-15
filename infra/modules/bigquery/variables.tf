variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "location" {
  description = "Dataset location (multi-region 'EU' by default)."
  type        = string
  default     = "EU"
}

variable "datasets" {
  description = <<-EOT
    Map of dataset_id => spec. Each spec supports:
      - description    : human description
      - editors        : list of IAM members getting roles/bigquery.dataEditor on the dataset
      - viewers        : list of IAM members getting roles/bigquery.dataViewer on the dataset
      - owners         : list of IAM members getting roles/bigquery.dataOwner on the dataset (rarely used)
      - default_table_expiration_ms : (optional) auto-expire tables (null = never)
  EOT
  type = map(object({
    description                 = string
    editors                     = optional(list(string), [])
    viewers                     = optional(list(string), [])
    owners                      = optional(list(string), [])
    default_table_expiration_ms = optional(number)
  }))
}

variable "labels" {
  description = "Labels propagated to all datasets."
  type        = map(string)
  default     = {}
}
