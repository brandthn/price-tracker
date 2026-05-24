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

# --- Worker image tags ----------------------------------------------------
# Tag (généralement SHORT_SHA git) de l'image Docker poussée en Artifact
# Registry par `gcloud builds submit`. Bumper après chaque rebuild :
# `git diff variables.tf` devient la timeline des déploiements workers.
# Tag immuable obligatoire (pas de `:latest`) — sinon Cloud Run ne voit
# pas le diff terraform et ne redéploie pas.

variable "worker_ingestion_image_tag" {
  description = "Tag de l'image worker-ingestion en AR. Doit exister dans le repo prt-prod-docker."
  type        = string
  default     = "6d4c0d2"
}

variable "worker_off_image_tag" {
  description = "Tag de l'image worker-off en AR. Doit exister dans le repo prt-prod-docker."
  type        = string
  default     = "e1e475c"
}
