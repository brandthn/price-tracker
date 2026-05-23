-- Table BQ Silver `open_prices_rejections` — produite par worker-ingestion (Phase 6.5).
--
-- Audit qualité : chaque ligne du snapshot HF qui ne passe pas la validation cleaner
-- (devise/pays/proof/prix/date) ou la validation EAN (checksum) ou la cohérence
-- discount est écrite ici avec son code de rejet, ses valeurs brutes, et le JSON
-- brut complet pour audit / re-traitement.
--
-- Source de vérité TERRAFORM : `bigquery_tables.tf` lit le JSON correspondant.
--
-- Partition : `pipeline_run_date` (DAY) → audit qualité par run de cron.
--   Différent de `open_prices_clean` (partitionné par price_date) car on consomme
--   cette table par fenêtre temporelle des runs, pas par date du prix observé.
-- Clustering : `reason` → SELECT … WHERE reason = 'INVALID_EAN' GROUP BY day.
--
-- Idempotence : un re-run du même jour TRUNCATE la partition `pipeline_run_date = today`
-- avant insert (cf. worker bq.py). Les MERGE sur id ne s'appliquent pas car
-- `id` peut être NULL (rejet avant tout parsing).

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_silver.open_prices_rejections`
(
  pipeline_run_date  DATE      NOT NULL OPTIONS(description="Date UTC du run. PARTITION."),
  id                 STRING             OPTIONS(description="PK Open Prices, NULL si rejet avant parsing."),
  product_code       STRING             OPTIONS(description="EAN brut potentiellement invalide."),
  reason             STRING    NOT NULL OPTIONS(description="Code de rejet (CLUSTERING)."),
  details            STRING             OPTIONS(description="Message explicatif du rejet."),
  currency           STRING             OPTIONS(description="Devise brute (avant validation)."),
  raw_price          STRING             OPTIONS(description="Prix brut stringifié."),
  raw_price_date     STRING             OPTIONS(description="Date brute stringifiée."),
  country_code       STRING             OPTIONS(description="Code pays brut."),
  proof_type         STRING             OPTIONS(description="Type de preuve brut."),
  rejected_at        TIMESTAMP NOT NULL OPTIONS(description="UTC timestamp du rejet."),
  raw_payload        STRING             OPTIONS(description="JSON brut complet de la ligne.")
)
PARTITION BY pipeline_run_date
CLUSTER BY reason
OPTIONS(
  description = "Lignes rejetées par worker-ingestion (audit qualité). Partition par date de run.",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "silver")]
);
