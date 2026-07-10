# Tags d'image des 6 workers OCR « un backend = un worker ».
#
# `skeleton` = l'image hello officielle Google (cf. local.cloud_run_skeleton_image
# dans cloud_run.tf) : `terraform apply` fonctionne AVANT le premier build, comme
# pour worker-indices / worker-alertes. Bumper au SHA réel après
# `gcloud builds submit . --config=workers/<worker>/cloudbuild.yaml`.
#
# Fichier additif : aucune variable existante n'est modifiée.

variable "worker_ocr_paddle_image_tag" {
  description = "Tag de l'image worker-ocr-paddle en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-paddle/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "skeleton"
}

variable "worker_ocr_ppocrv4_image_tag" {
  description = "Tag de l'image worker-ocr-ppocrv4 en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-ppocrv4/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "skeleton"
}

variable "worker_ocr_vlm_moondream_image_tag" {
  description = "Tag de l'image worker-ocr-vlm-moondream en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-vlm-moondream/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "skeleton"
}

variable "worker_ocr_vlm_groq_image_tag" {
  description = "Tag de l'image worker-ocr-vlm-groq en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-vlm-groq/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "skeleton"
}

variable "worker_ocr_vlm_receipt_image_tag" {
  description = "Tag de l'image worker-ocr-vlm-receipt en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-vlm-receipt/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "skeleton"
}

variable "worker_ocr_vlm_scratch_image_tag" {
  description = "Tag de l'image worker-ocr-vlm-scratch en AR. Bumper après chaque build (gcloud builds submit . --config=workers/ocr-vlm-scratch/cloudbuild.yaml). 'skeleton' = image hello (pré-build)."
  type        = string
  default     = "skeleton"
}

# --- Chemins GCS des poids modèle (bucket models existant) ----------------
# Les workers à poids locaux téléchargent ces objets au démarrage (lifespan).
# Versionner = pointer un nouveau préfixe (v2/...), pas écraser l'objet.

variable "ocr_vlm_moondream_model_gcs_uri" {
  description = "URI gs:// des poids Moondream 0.5B int8 (.mf). Uploader une fois : gsutil cp dev_ocr/data/models/moondream-0_5b-int8.mf gs://<project>-models/vlm/moondream/v1/"
  type        = string
  default     = "vlm/moondream/v1/moondream-0_5b-int8.mf"
}

variable "ocr_vlm_receipt_model_gcs_uri" {
  description = "Objet GCS (relatif au bucket models) du checkpoint mergé receipt-vlm-500m (.pt)."
  type        = string
  default     = "vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt"
}

variable "ocr_vlm_scratch_model_gcs_uri" {
  description = "Objet GCS (relatif au bucket models) du checkpoint OCR-VLM from-scratch (.pt). Défaut = epoch050 (Stage B), meilleur checkpoint réel : ANLS 0.183 vs 0.170 et product_recall ×2 vs epoch040 (cf. checkpoints/eval_epoch0*.json)."
  type        = string
  default     = "vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt"
}

variable "ocr_vlm_scratch_tokenizer_gcs_uri" {
  description = "Objet GCS (relatif au bucket models) du tokenizer caractère du modèle from-scratch (.json)."
  type        = string
  default     = "vlm/ocr-vlm-scratch/v1/tokenizer_20260607_0900.json"
}
