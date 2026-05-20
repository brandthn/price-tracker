variable "project_id" {
  description = "ID du projet GCP"
  type        = string
}

variable "region" {
  description = "Région Cloud Run / Scheduler (ex. europe-west9)"
  type        = string
  default     = "europe-west9"
}

variable "bq_location" {
  description = "Emplacement du dataset BigQuery (souvent EU)"
  type        = string
  default     = "EU"
}

variable "dataset_id" {
  description = "Identifiant du dataset analytique"
  type        = string
  default     = "open_prices_dw"
}

variable "bucket_prefix" {
  description = "Préfixe des noms de buckets (suffixe -bronze / -signals / -artifacts)"
  type        = string
  default     = "pa-open-prices"
}

variable "artifact_repository_id" {
  description = "ID du dépôt Artifact Registry Docker"
  type        = string
  default     = "open-prices"
}

variable "worker_image_tag" {
  description = "Tag d’image à déployer sur Cloud Run (ex. latest ou sha Git)"
  type        = string
  default     = "latest"
}

variable "scheduler_timezone" {
  description = "Fuseau horaire des jobs Cloud Scheduler"
  type        = string
  default     = "Europe/Paris"
}

variable "create_cloud_run_services" {
  description = "true après publication des images dans Artifact Registry"
  type        = bool
  default     = false
}
