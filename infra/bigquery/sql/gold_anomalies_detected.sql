-- Table BQ Gold `anomalies_detected` — produite par worker-indices (Phase 9.1).
--
-- Contenu : prix medians hebdomadaires avec |z-score| >= 3 vs historique du
-- couple (product_code, store_brand_normalized). Alimente le worker-alertes
-- pour generer les signaux a destination des utilisateurs.
--
-- Source de verite TERRAFORM : `infra/envs/prod/bigquery_tables.tf` lit
-- `schemas/gold_anomalies_detected.json`. Le worker fait `CREATE OR REPLACE
-- TABLE` a chaque run.
--
-- Partition : `week_start_date` -> filtre fenetre 8 semaines.
-- Clustering : (product_code, store_brand_normalized) -> agregations produit/enseigne.

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_gold.anomalies_detected`
(
  week_start_date          DATE    NOT NULL OPTIONS(description="Semaine ou l'anomalie a ete detectee."),
  product_code             STRING           OPTIONS(description="EAN du produit concerne."),
  store_brand_normalized   STRING           OPTIONS(description="Enseigne normalisee."),
  median_price_eur         FLOAT64          OPTIONS(description="Prix median de la semaine."),
  observations             INT64            OPTIONS(description="Nombre de releves utilises."),
  mean_med                 FLOAT64          OPTIONS(description="Moyenne des medianes (fenetre historique)."),
  std_med                  FLOAT64          OPTIONS(description="Ecart-type des medianes (fenetre)."),
  z_score                  FLOAT64          OPTIONS(description="z = (median - mean) / std. |z| >= 3 = alerte.")
)
PARTITION BY week_start_date
CLUSTER BY product_code, store_brand_normalized
OPTIONS(
  description = "Anomalies de prix (z-score >= 3) — alimente par worker-indices (cron 05h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "gold")]
);
