# Tables BigQuery Silver — créées en Phase 6 (workers ingestion + OFF).
#
# Conventions :
# - Schéma : JSON versionné dans `infra/bigquery/schemas/<table>.json`.
#   La copie SQL human-readable est dans `infra/bigquery/sql/<table>.sql`
#   pour code review et recréation manuelle d'urgence (`bq query --use_legacy_sql=false`).
# - Partitionnement + clustering : voir le DDL SQL (commentaires détaillés).
# - Pas de `deletion_protection` : projet école, on veut pouvoir détruire
#   librement via `terraform destroy`. Les tables sont reconstruites en <1s
#   à l'apply suivant, et la donnée est ré-ingérable depuis HF Open Prices.
#
# Pourquoi Terraform et pas `bq mk` manuel ? Le schéma vit dans le repo, le
# plan/apply trace toute évolution (drift = bug). Les modifs additives
# (nouvelle colonne) passent en `terraform apply` ; les modifs destructives
# (drop/rename) demandent un drop-recreate explicite.

locals {
  bq_silver_dataset = "${replace(var.name_prefix, "-", "_")}_silver"

  # Labels communs aux tables Silver. Le label `component=silver-<role>` permet
  # de filtrer côté Cloud Logging / cost reports.
  bq_silver_labels = merge(var.labels, { component = "silver" })
}

# --- open_prices_clean (Phase 6.1) ---------------------------------------
resource "google_bigquery_table" "open_prices_clean" {
  project    = var.project_id
  dataset_id = local.bq_silver_dataset
  table_id   = "open_prices_clean"

  description         = "Open Prices nettoye (France) — worker-ingestion (cron 03h UTC)."
  deletion_protection = false
  labels              = local.bq_silver_labels

  schema = file("${path.module}/../../bigquery/schemas/silver_open_prices_clean.json")

  time_partitioning {
    type  = "DAY"
    field = "date"
  }

  clustering = ["kind", "product_code"]

  depends_on = [module.bigquery]
}

# --- catalogue_produits (Phase 6.2) --------------------------------------
resource "google_bigquery_table" "catalogue_produits" {
  project    = var.project_id
  dataset_id = local.bq_silver_dataset
  table_id   = "catalogue_produits"

  description         = "Catalogue produits enrichi via OpenFoodFacts — worker-off (cron 04h UTC)."
  deletion_protection = false
  labels              = local.bq_silver_labels

  schema = file("${path.module}/../../bigquery/schemas/silver_catalogue_produits.json")

  # Pas de partitionnement : table de référence ~10⁴-10⁵ lignes, les
  # requêtes filtrent par `ean` (clustering) — un scan complet reste
  # cheap. Voir le DDL SQL (`infra/bigquery/sql/silver_catalogue_produits.sql`).
  clustering = ["ean"]

  depends_on = [module.bigquery]
}
