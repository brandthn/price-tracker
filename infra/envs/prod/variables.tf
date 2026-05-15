variable "project_id" {
  description = "GCP project ID."
  type        = string
  default     = "price-tracker-prod-01"
}

variable "region" {
  description = "Default compute region."
  type        = string
  default     = "europe-west1"
}

variable "tf_state_bucket" {
  description = "Name of the (already existing) GCS bucket holding Terraform state. Imported into Terraform on first apply."
  type        = string
  default     = "price-tracker-prod-01-tf-state"
}

variable "name_prefix" {
  description = "Resource name prefix for project-scoped resources."
  type        = string
  default     = "prt-prod"
}

variable "labels" {
  description = "Common labels applied to resources supporting them."
  type        = map(string)
  default = {
    app        = "price-tracker"
    env        = "prod"
    managed_by = "terraform"
  }
}
