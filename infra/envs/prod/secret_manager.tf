# secrets. pas de cle Firebase (org policy interdit les cles JSON, ADC via SA).
module "secrets" {
  source = "../../modules/secret_manager"

  project_id = var.project_id
  labels     = merge(var.labels, { component = "secret-manager" })

  secrets = {
    "${var.name_prefix}-cloudsql-password" = {
      description = "Mdp user applicatif Cloud SQL."
      accessors   = [local.backend_sa, local.worker_sa]
    }
    "${var.name_prefix}-hf-token" = {
      description = "HuggingFace API token."
      accessors   = [local.worker_sa]
    }
    "${var.name_prefix}-groq-api-key" = {
      description = "Groq API key (worker OCR)."
      accessors   = [local.worker_sa]
    }
  }
}
