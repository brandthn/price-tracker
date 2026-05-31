-- Table BQ Gold `rankings_produits` — produite par worker-indices (Phase 9.1).
--
-- Contenu : Top 500 produits ayant subi la plus forte hausse de prix median
-- entre deux semaines consecutives. Lecture frontend (hall of shame).
--
-- Source de verite TERRAFORM : `infra/envs/prod/bigquery_tables.tf` lit
-- `schemas/gold_rankings_produits.json`. Le worker fait `CREATE OR REPLACE
-- TABLE` a chaque run.
--
-- Partition : `reference_week` -> pruning par fenetre courante.
-- Clustering : (product_code) -> deeplinks frontend `/products/{ean}/history`.

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_gold.rankings_produits`
(
  reference_week   DATE    NOT NULL OPTIONS(description="Semaine de reference du calcul."),
  product_code     STRING  NOT NULL OPTIONS(description="EAN-13 ou EAN-8 du produit."),
  prev_median      FLOAT64          OPTIONS(description="Mediane semaine N-1."),
  curr_median      FLOAT64          OPTIONS(description="Mediane semaine N."),
  pct_change       FLOAT64          OPTIONS(description="(curr - prev) / prev. Top 500 hausses.")
)
PARTITION BY reference_week
CLUSTER BY product_code
OPTIONS(
  description = "Top 500 hausses produits semaine sur semaine — alimente par worker-indices (cron 05h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "gold")]
);
