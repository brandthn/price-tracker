-- Table BQ Gold `indices_inflation` — produite par worker-indices (Phase 9.1).
--
-- Contenu : indice chaine base 100 a la premiere semaine disponible, calcule
-- sur la mediane hebdomadaire par enseigne x pays. Lecture frontend :
-- `index_value = 103.5` => +3.5 % vs semaine de base.
--
-- Source de verite TERRAFORM : `infra/envs/prod/bigquery_tables.tf` lit
-- `schemas/gold_indices_inflation.json`. Le worker fait `CREATE OR REPLACE
-- TABLE` a chaque run (recalcul complet de la fenetre 12 semaines).
--
-- Partition : `week_start_date` -> pruning analytique sur fenetre temporelle.
-- Clustering : (country_code, store_brand_normalized) idem agregats.

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_gold.indices_inflation`
(
  week_start_date          DATE    NOT NULL OPTIONS(description="Lundi de la semaine ISO."),
  store_brand_normalized   STRING  NOT NULL OPTIONS(description="Enseigne normalisee."),
  country_code             STRING  NOT NULL OPTIONS(description="ISO-3166 alpha-2."),
  observations             INT64            OPTIONS(description="Nombre de releves pour la mediane."),
  median_price_eur         FLOAT64          OPTIONS(description="Prix median hebdomadaire."),
  base_price               FLOAT64          OPTIONS(description="Mediane de la premiere semaine (base 100)."),
  index_value              FLOAT64          OPTIONS(description="Indice chaine base 100.")
)
PARTITION BY week_start_date
CLUSTER BY country_code, store_brand_normalized
OPTIONS(
  description = "Indice inflation base 100 par enseigne x pays — alimente par worker-indices (cron 05h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "gold")]
);
