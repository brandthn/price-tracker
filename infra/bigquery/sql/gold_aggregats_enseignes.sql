-- Table BQ Gold `aggregats_enseignes` — produite par worker-indices (Phase 9.1).
--
-- Source de verite TERRAFORM : `infra/envs/prod/bigquery_tables.tf` lit le fichier
-- `schemas/gold_aggregats_enseignes.json`. Ce DDL humain est conserve pour
-- code review et recreation manuelle d'urgence.
--
-- Contenu : prix moyen et median par semaine x enseigne x pays. Le worker fait
-- un DELETE+INSERT sur les 12 dernieres semaines a chaque run (idempotent).
--
-- Partition : `week_start_date` (DAY) -> pruning sur les vues frontend qui
-- filtrent toujours par fenetre temporelle (`WHERE week_start_date >= ...`).
-- Clustering : (country_code, store_brand_normalized) -> couvre tous les
-- patterns d'agregation Gold (national, par enseigne).

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_gold.aggregats_enseignes`
(
  week_start_date          DATE    NOT NULL OPTIONS(description="Lundi de la semaine ISO. PARTITION."),
  store_brand_normalized   STRING  NOT NULL OPTIONS(description="Enseigne normalisee."),
  country_code             STRING  NOT NULL OPTIONS(description="ISO-3166 alpha-2."),
  observations             INT64   NOT NULL OPTIONS(description="Nombre de releves de prix."),
  avg_price_eur            FLOAT64          OPTIONS(description="Prix moyen (sensible aux outliers)."),
  median_price_eur         FLOAT64          OPTIONS(description="Prix median APPROX_QUANTILES. Reference.")
)
PARTITION BY week_start_date
CLUSTER BY country_code, store_brand_normalized
OPTIONS(
  description = "Agregats hebdomadaires par enseigne x pays — alimente par worker-indices (cron 05h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "gold")]
);
