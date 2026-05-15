# BigQuery datasets — data warehouse (Bronze/Silver/Gold modèle Medallion).
# - silver  : Open Prices nettoyés + catalogue produits (alimenté par workers
#             ingestion + OFF en Phase 6).
# - gold    : indices d'inflation, agrégats enseignes, rankings (worker indices
#             en Phase 9.1).
# - ml      : datasets d'entraînement / fine-tuning (OCR, embeddings) — optionnel
#             pour les phases ML. Réservé tôt pour ne pas avoir à recréer.
#
# IAM dataset-level (préféré aux rôles projet) :
#  - worker-sa  : dataEditor partout (écrit les pipelines)
#  - backend-sa : dataViewer silver+gold (lit pour l'observatoire)
#                 dataViewer ml (lecture seule, le ML reste worker-side)
module "bigquery" {
  source = "../../modules/bigquery"

  project_id = var.project_id
  location   = "EU"
  labels     = merge(var.labels, { component = "bigquery" })

  datasets = {
    "${replace(var.name_prefix, "-", "_")}_silver" = {
      description = "Bronze→Silver : Open Prices nettoyés, catalogue produits enrichi OFF."
      editors     = [local.worker_sa]
      viewers     = [local.backend_sa]
    }
    "${replace(var.name_prefix, "-", "_")}_gold" = {
      description = "Silver→Gold : indices d'inflation (Laspeyres), agrégats enseignes, rankings."
      editors     = [local.worker_sa]
      viewers     = [local.backend_sa]
    }
    "${replace(var.name_prefix, "-", "_")}_ml" = {
      description = "Datasets d'entraînement/évaluation ML (OCR, embeddings, monitoring qualité)."
      editors     = [local.worker_sa]
      viewers     = [local.backend_sa]
    }
  }
}
