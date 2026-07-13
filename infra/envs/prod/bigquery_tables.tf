# tables BQ silver + gold. schema JSON dans infra/bigquery/schemas/. pas de
# deletion_protection (recreable a l'apply).

locals {
  bq_silver_dataset = "${replace(var.name_prefix, "-", "_")}_silver"
  bq_gold_dataset   = "${replace(var.name_prefix, "-", "_")}_gold"

  bq_silver_labels = merge(var.labels, { component = "silver" })
  bq_gold_labels   = merge(var.labels, { component = "gold" })
}

# open_prices_clean : partition price_date, clustering pays/enseigne/EAN
resource "google_bigquery_table" "open_prices_clean" {
  project    = var.project_id
  dataset_id = local.bq_silver_dataset
  table_id   = "open_prices_clean"

  description         = "Open Prices nettoyé + enrichi (FR + DOM-TOM) — worker-ingestion (cron 03h UTC)."
  deletion_protection = false
  labels              = local.bq_silver_labels

  schema = file("${path.module}/../../bigquery/schemas/silver_open_prices_clean.json")

  time_partitioning {
    type  = "DAY"
    field = "price_date"
  }

  clustering = ["country_code", "store_brand_normalized", "product_code"]

  depends_on = [module.bigquery]
}

# open_prices_rejections : audit qualite, partition pipeline_run_date, clustering reason
resource "google_bigquery_table" "open_prices_rejections" {
  project    = var.project_id
  dataset_id = local.bq_silver_dataset
  table_id   = "open_prices_rejections"

  description         = "Lignes rejetées par worker-ingestion (audit qualité). Partition par date de run."
  deletion_protection = false
  labels              = local.bq_silver_labels

  schema = file("${path.module}/../../bigquery/schemas/silver_open_prices_rejections.json")

  time_partitioning {
    type  = "DAY"
    field = "pipeline_run_date"
  }

  clustering = ["reason"]

  depends_on = [module.bigquery]
}

# catalogue_produits : table de reference, clustering ean, pas de partition
resource "google_bigquery_table" "catalogue_produits" {
  project    = var.project_id
  dataset_id = local.bq_silver_dataset
  table_id   = "catalogue_produits"

  description         = "Catalogue produits enrichi via OpenFoodFacts — worker-off (cron 04h UTC)."
  deletion_protection = false
  labels              = local.bq_silver_labels

  schema = file("${path.module}/../../bigquery/schemas/silver_catalogue_produits.json")

  clustering = ["ean"]

  depends_on = [module.bigquery]
}

# tables BQ gold, alimentees par worker-indices (DELETE+INSERT pour garder
# partition/clustering TF). partition = colonne temporelle dominante.

resource "google_bigquery_table" "aggregats_enseignes" {
  project    = var.project_id
  dataset_id = local.bq_gold_dataset
  table_id   = "aggregats_enseignes"

  description         = "Agrégats hebdomadaires par enseigne × pays — worker-indices (cron 05h UTC)."
  deletion_protection = false
  labels              = local.bq_gold_labels

  schema = file("${path.module}/../../bigquery/schemas/gold_aggregats_enseignes.json")

  time_partitioning {
    type  = "DAY"
    field = "week_start_date"
  }

  clustering = ["country_code", "store_brand_normalized"]

  depends_on = [module.bigquery]
}

resource "google_bigquery_table" "indices_inflation" {
  project    = var.project_id
  dataset_id = local.bq_gold_dataset
  table_id   = "indices_inflation"

  description         = "Indice inflation base 100 par enseigne × pays — worker-indices (cron 05h UTC)."
  deletion_protection = false
  labels              = local.bq_gold_labels

  schema = file("${path.module}/../../bigquery/schemas/gold_indices_inflation.json")

  time_partitioning {
    type  = "DAY"
    field = "week_start_date"
  }

  clustering = ["country_code", "store_brand_normalized"]

  depends_on = [module.bigquery]
}

resource "google_bigquery_table" "rankings_produits" {
  project    = var.project_id
  dataset_id = local.bq_gold_dataset
  table_id   = "rankings_produits"

  description         = "Top 500 hausses produits semaine sur semaine — worker-indices (cron 05h UTC)."
  deletion_protection = false
  labels              = local.bq_gold_labels

  schema = file("${path.module}/../../bigquery/schemas/gold_rankings_produits.json")

  time_partitioning {
    type  = "DAY"
    field = "reference_week"
  }

  clustering = ["product_code"]

  depends_on = [module.bigquery]
}

resource "google_bigquery_table" "anomalies_detected" {
  project    = var.project_id
  dataset_id = local.bq_gold_dataset
  table_id   = "anomalies_detected"

  description         = "Anomalies prix (|z| >= 3) — worker-indices (cron 05h UTC), consommé par worker-alertes."
  deletion_protection = false
  labels              = local.bq_gold_labels

  schema = file("${path.module}/../../bigquery/schemas/gold_anomalies_detected.json")

  time_partitioning {
    type  = "DAY"
    field = "week_start_date"
  }

  clustering = ["product_code", "store_brand_normalized"]

  depends_on = [module.bigquery]
}
