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
  description = "GCS bucket holding Terraform state."
  type        = string
  default     = "price-tracker-prod-01-tf-state"
}

variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
  default     = "prt-prod"
}

variable "labels" {
  description = "Common labels."
  type        = map(string)
  default = {
    app        = "price-tracker"
    env        = "prod"
    managed_by = "terraform"
  }
}

# image tags (git short sha, immuable)

variable "worker_ingestion_image_tag" {
  type    = string
  default = "6d4c0d2"
}

variable "worker_off_image_tag" {
  type    = string
  default = "43d4669"
}

variable "backend_image_tag" {
  type    = string
  default = "f34364d"
}

variable "backend_auth_enabled" {
  description = "true = verif JWT Firebase reelle. false = mode demo (bypass)."
  type        = bool
  default     = true
}

variable "worker_ocr_image_tag" {
  type    = string
  default = "90598e4"
}

variable "worker_ocr_llm_image_tag" {
  type    = string
  default = "08c2365"
}

variable "worker_ocr_paddle_image_tag" {
  type    = string
  default = "1672d2d"
}

variable "worker_ocr_vlm_moondream_image_tag" {
  type    = string
  default = "ebc73d0"
}

variable "worker_ocr_vlm_scratch_image_tag" {
  type    = string
  default = "10d90ed"
}

variable "ocr_vlm_moondream_model_gcs_uri" {
  type    = string
  default = "vlm/moondream/v1/moondream-0_5b-int8.mf"
}

variable "ocr_vlm_scratch_model_gcs_uri" {
  type    = string
  default = "vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt"
}

variable "ocr_vlm_scratch_tokenizer_gcs_uri" {
  type    = string
  default = "vlm/ocr-vlm-scratch/v1/tokenizer_20260607_0900.json"
}

variable "worker_indices_image_tag" {
  type    = string
  default = "3576a7f"
}

variable "worker_alertes_image_tag" {
  type    = string
  default = "3576a7f"
}

variable "frontend_image_tag" {
  type    = string
  default = "9b79e0e"
}

variable "frontend_cors_origins" {
  description = "Origines autorisees CORS bucket bronze (signed urls)."
  type        = list(string)
  default     = ["*"]
}
