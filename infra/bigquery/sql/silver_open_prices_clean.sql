-- Table BQ Silver `open_prices_clean` — produite par worker-ingestion (Phase 6.1).
--
-- Source : snapshot quotidien HuggingFace `openfoodfacts/open-prices` filtré FR,
-- dédupé sur `id`, écrit en MERGE depuis une staging table.
--
-- Source de vérité TERRAFORM : `infra/envs/prod/bigquery_tables.tf` lit le
-- fichier `schemas/silver_open_prices_clean.json` correspondant. Ce DDL
-- humain est conservé pour code review et recréation manuelle d'urgence
-- (`bq query --use_legacy_sql=false < silver_open_prices_clean.sql`).
--
-- Partition : `date` (DAY) → BQ pruning sur range de dates dans Gold.
-- Clustering : (kind, product_code) → look-ups par EAN et tri PRODUCT vs CATEGORY.

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_silver.open_prices_clean`
(
  id                STRING    NOT NULL OPTIONS(description="PK Open Prices, clé de MERGE."),
  date              DATE      NOT NULL OPTIONS(description="Date du prix observé. Colonne de partition."),
  product_code      STRING             OPTIONS(description="EAN/barcode. NULL pour les `kind=CATEGORY`."),
  product_name      STRING             OPTIONS(description="Libellé brut tel que saisi par le contributeur."),
  price             FLOAT64            OPTIONS(description="Prix unitaire dans `currency`."),
  currency          STRING             OPTIONS(description="ISO-4217 (EUR pour la France)."),
  location_id       INT64              OPTIONS(description="Open Prices location id (joint sur master OFF)."),
  location_osm_name STRING             OPTIONS(description="Nom OSM du magasin (lisible humain)."),
  country_code      STRING             OPTIONS(description="ISO-3166 alpha-2. `FR` exclusivement après filtre worker."),
  category_tag      STRING             OPTIONS(description="OFF category tag (ex: `fr:oeufs`). NULL si kind=PRODUCT."),
  kind              STRING    NOT NULL OPTIONS(description="PRODUCT | CATEGORY. Upper-case enforced côté worker."),
  source            STRING    NOT NULL OPTIONS(description="Provenance — toujours `hf-open-prices` pour cette table."),
  ingested_at       TIMESTAMP NOT NULL OPTIONS(description="UTC timestamp du run worker qui a produit la ligne.")
)
PARTITION BY date
CLUSTER BY kind, product_code
OPTIONS(
  description = "Open Prices nettoyé (France) — alimenté quotidiennement par worker-ingestion (cron 03h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "silver")]
);
