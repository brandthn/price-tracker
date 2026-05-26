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
  default     = "13d832b"
}

variable "backend_image_tag" {
  description = "Tag de l'image backend FastAPI en AR. Doit exister dans le repo prt-prod-docker. Mis à jour à chaque déploiement Phase 7+."
  type        = string
  # Placeholder skeleton — le 1er apply après le 1er build remplace par le SHA réel.
  default = "63c5d4a"
}

variable "worker_ocr_image_tag" {
  description = "Tag de l'image worker-ocr en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr/cloudbuild.yaml)."
  type        = string
  default     = "63c5d4a"
}

variable "worker_indices_image_tag" {
  description = "Tag de l'image worker-indices en AR. Bumper après chaque build (gcloud builds submit . --config=workers/indices/cloudbuild.yaml)."
  type        = string
  # Placeholder skeleton — Cloud Run garde l'image `us-docker.pkg.dev/cloudrun/container/hello`
  # tant que ce default n'est pas remplacé par un SHA réel pushé en AR.
  default = "phase9-skeleton"
}

variable "worker_alertes_image_tag" {
  description = "Tag de l'image worker-alertes en AR. Bumper après chaque build (gcloud builds submit . --config=workers/alertes/cloudbuild.yaml)."
  type        = string
  default     = "phase9-skeleton"
}

variable "frontend_image_tag" {
  description = "Tag de l'image frontend Next.js en AR. Bumper après chaque build (gcloud builds submit . --config=frontend/cloudbuild.yaml)."
  type        = string
  # Placeholder skeleton — le 1er apply après le 1er build remplace par le SHA réel.
  default = "b518872"
}

variable "frontend_cors_origins" {
  description = <<-EOT
    Origines autorisées par le bucket bronze pour les Signed URLs PUT/GET depuis
    le navigateur. `["*"]` en mode démo Phase 10. À restreindre quand l'URL Cloud
    Run du frontend est stable (ex: ["https://prt-prod-frontend-XXX-ew.a.run.app"]).
  EOT
  type        = list(string)
  default     = ["*"]
}
