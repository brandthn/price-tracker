-- Table BQ Silver `open_prices_clean` — produite par worker-ingestion (Phase 6.1 / v2 Phase 6.5).
--
-- Source : snapshot quotidien HuggingFace `openfoodfacts/open-prices`, filtré sur les
-- pays acceptés (FR métropole + DOM-TOM), passé au cleaner (validation devise/pays/proof/
-- prix/date), enrichi (store_brand normalisée, city standardisée, EAN checksum, week_start_date,
-- flag IQR), puis écrit en MERGE depuis une staging table sur la clé `id`.
--
-- Source de vérité TERRAFORM : `infra/envs/prod/bigquery_tables.tf` lit le fichier
-- `schemas/silver_open_prices_clean.json` correspondant. Ce DDL humain est conservé
-- pour code review et recréation manuelle d'urgence
-- (`bq query --use_legacy_sql=false < silver_open_prices_clean.sql`).
--
-- Partition : `price_date` (DAY) → BQ pruning sur les fenêtres analytiques Gold
--   (`WHERE price_date BETWEEN ...`), qui sont les patterns d'accès dominants.
-- Clustering : (country_code, store_brand_normalized, product_code) → couvre les
--   agrégats Gold (indices régionaux par enseigne, lookups par EAN, rankings enseignes).

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_silver.open_prices_clean`
(
  id                          STRING    NOT NULL OPTIONS(description="PK Open Prices, clé de MERGE."),
  pipeline_run_date           DATE      NOT NULL OPTIONS(description="Date UTC du run worker (traçabilité)."),
  price_date                  DATE      NOT NULL OPTIONS(description="Date du relevé de prix. PARTITION."),
  week_start_date             DATE               OPTIONS(description="Lundi de la semaine ISO contenant price_date."),
  product_code                STRING             OPTIONS(description="EAN-13 ou EAN-8 validé (checksum)."),
  price_eur                   FLOAT64   NOT NULL OPTIONS(description="Prix unitaire en euros (0.01 ≤ p ≤ 500)."),
  price_eur_decimal           STRING             OPTIONS(description="Prix en Decimal string (précision comptable)."),
  price_without_discount_eur  FLOAT64            OPTIONS(description="Prix sans remise (NULL si non renseigné)."),
  price_is_discounted         BOOL               OPTIONS(description="True si le relevé est en promotion."),
  currency                    STRING    NOT NULL OPTIONS(description="ISO-4217. Toujours EUR (autres rejetées)."),
  proof_type                  STRING             OPTIONS(description="RECEIPT | PRICE_TAG | SHOP_IMPORT."),
  country_code                STRING    NOT NULL OPTIONS(description="ISO-3166 alpha-2. FR + DOM-TOM."),
  store_brand                 STRING             OPTIONS(description="Adresse OSM brute du magasin."),
  store_brand_normalized      STRING             OPTIONS(description="Enseigne canonique (Carrefour, Lidl, …)."),
  location_id                 STRING             OPTIONS(description="Open Prices location id."),
  location_name               STRING             OPTIONS(description="Nom OSM du magasin."),
  location_osm_display_name   STRING             OPTIONS(description="Adresse affichable complète OSM."),
  city                        STRING             OPTIONS(description="Ville normalisée (title-case sans arrondissement)."),
  postcode                    STRING             OPTIONS(description="Code postal (string)."),
  latitude                    FLOAT64            OPTIONS(description="Latitude GPS OSM."),
  longitude                   FLOAT64            OPTIONS(description="Longitude GPS OSM."),
  iqr_outlier                 BOOL               OPTIONS(description="True si prix hors [Q1-3·IQR, Q3+3·IQR] par produit."),
  source                      STRING    NOT NULL OPTIONS(description="Provenance. Toujours 'hf-open-prices'."),
  ingested_at                 TIMESTAMP NOT NULL OPTIONS(description="UTC timestamp précis du run."),
  raw_payload                 STRING             OPTIONS(description="JSON brut de la ligne HF (audit).")
)
PARTITION BY price_date
CLUSTER BY country_code, store_brand_normalized, product_code
OPTIONS(
  description = "Open Prices nettoyé + enrichi (FR + DOM-TOM) — alimenté quotidiennement par worker-ingestion (cron 03h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "silver")]
);
