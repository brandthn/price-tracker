# Secrets vides en Phase 2 (containers + IAM uniquement).
# Les valeurs sont populées soit :
#   - manuellement (firebase-admin SDK JSON, hf-token HuggingFace)
#   - automatiquement en Phase 4 (cloudsql-password généré par Terraform)
module "secrets" {
  source = "../../modules/secret_manager"

  project_id = var.project_id
  labels     = merge(var.labels, { component = "secret-manager" })

  secrets = {
    "${var.name_prefix}-cloudsql-password" = {
      description = "Mot de passe du user applicatif sur Cloud SQL. Généré en Phase 4."
      accessors   = [local.backend_sa, local.worker_sa]
    }
    "${var.name_prefix}-firebase-admin" = {
      description = "Firebase Admin SDK service account JSON (pour la vérification des JWT côté backend)."
      accessors   = [local.backend_sa]
    }
    "${var.name_prefix}-hf-token" = {
      description = "HuggingFace API token (worker ingestion lit le snapshot Open Prices)."
      accessors   = [local.worker_sa]
    }
  }
}
