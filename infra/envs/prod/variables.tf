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
  default     = "43d4669"
}

variable "backend_image_tag" {
  description = "Tag de l'image backend FastAPI en AR. Doit exister dans le repo prt-prod-docker. Mis à jour à chaque déploiement Phase 7+."
  type        = string
  default     = "23e5aa4"
}

variable "backend_auth_enabled" {
  description = <<-EOT
    Active la vérification réelle des JWT Firebase côté backend (PRT_ENV=prod +
    PRT_AUTH_DISABLE=0). `false` = mode démo (bypass, tous les appels mappés sur
    un user fake — pas de per-user).

    !! Passer à `true` UNIQUEMENT après avoir déployé le frontend avec sa config
    Firebase (NEXT_PUBLIC_FIREBASE_*) : sinon le front démo envoie un Bearer
    invalide → 401. Voir docs/phase-11-auth-handoff.md.
  EOT
  type        = bool
  default     = true
}

variable "worker_ocr_image_tag" {
  description = "Tag de l'image worker-ocr en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr/cloudbuild.yaml)."
  type        = string
  default     = "90598e4"
}

variable "worker_ocr_llm_image_tag" {
  description = "Tag de l'image worker-ocr-llm (OCR tier-2) en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-llm/cloudbuild.yaml)."
  type        = string
  default = "08c2365"
}

variable "worker_ocr_paddle_image_tag" {
  description = "Tag de l'image worker-ocr-paddle en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-paddle/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "1672d2d"
}

variable "worker_ocr_vlm_moondream_image_tag" {
  description = "Tag de l'image worker-ocr-vlm-moondream en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-vlm-moondream/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "1672d2d"
}

variable "worker_ocr_vlm_scratch_image_tag" {
  description = "Tag de l'image worker-ocr-vlm-scratch en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-vlm-scratch/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "1672d2d"
}

variable "ocr_vlm_moondream_model_gcs_uri" {
  description = "Objet GCS (relatif au bucket models) des poids Moondream 0.5B int8 (.mf), téléchargés au cold start."
  type        = string
  default     = "vlm/moondream/v1/moondream-0_5b-int8.mf"
}

variable "ocr_vlm_scratch_model_gcs_uri" {
  description = "Objet GCS (relatif au bucket models) du checkpoint OCR-VLM from-scratch (.pt). Défaut = epoch050 (meilleur ANLS/product_recall réel)."
  type        = string
  default     = "vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt"
}

variable "ocr_vlm_scratch_tokenizer_gcs_uri" {
  description = "Objet GCS (relatif au bucket models) du tokenizer caractère du modèle from-scratch (.json)."
  type        = string
  default     = "vlm/ocr-vlm-scratch/v1/tokenizer_20260607_0900.json"
}

variable "worker_indices_image_tag" {
  description = "Tag de l'image worker-indices en AR. Bumper après chaque build (gcloud builds submit . --config=workers/indices/cloudbuild.yaml)."
  type        = string
  default = "3576a7f"
}

variable "worker_alertes_image_tag" {
  description = "Tag de l'image worker-alertes en AR. Bumper après chaque build (gcloud builds submit . --config=workers/alertes/cloudbuild.yaml)."
  type        = string
  default     = "3576a7f"
}

variable "frontend_image_tag" {
  description = "Tag de l'image frontend Next.js en AR. Bumper après chaque build (gcloud builds submit . --config=frontend/cloudbuild.yaml)."
  type        = string
  default     = "bb0d230"
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
