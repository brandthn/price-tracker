# datasets BQ silver/gold/ml. IAM dataset-level : worker dataEditor, backend dataViewer.
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
      description = "Datasets ML (OCR, embeddings)."
      editors     = [local.worker_sa]
      viewers     = [local.backend_sa]
    }
  }
}
