-- Table BQ Silver `catalogue_produits` — produite par worker-off (Phase 6.2).
--
-- Source : Open Food Facts API (https://world.openfoodfacts.org/api/v2/product/<ean>).
-- Le worker prend en entrée la liste des EAN distincts présents dans
-- `open_prices_clean` mais absents de cette table ; pour chacun il interroge
-- OFF (rate-limit 15 req/min), enrichit ces champs et écrit un MERGE sur `ean`.
--
-- Le miroir Cloud SQL `products` (pgvector) est mis à jour dans le même run
-- avec les mêmes champs + l'embedding Vertex AI text-embedding-004 (dim 768).
-- Le BQ catalogue sert l'observatoire (analyses agrégées) ; le pgvector sert
-- la similarité produit (substituts).
--
-- Source de vérité TERRAFORM : `infra/envs/prod/bigquery_tables.tf` + `schemas/silver_catalogue_produits.json`.

CREATE TABLE IF NOT EXISTS `price-tracker-prod-01.prt_prod_silver.catalogue_produits`
(
  ean          STRING    NOT NULL OPTIONS(description="EAN/barcode produit. PK et clé de MERGE."),
  name         STRING             OPTIONS(description="Libellé OFF (product_name_fr fallback product_name)."),
  brand        STRING             OPTIONS(description="Marque principale (premier élément de `brands`)."),
  category_l1  STRING             OPTIONS(description="Catégorie OFF niveau 1 (ex: en:foods)."),
  category_l2  STRING             OPTIONS(description="Catégorie OFF niveau 2."),
  category_l3  STRING             OPTIONS(description="Catégorie OFF niveau 3 (utilisée pour l'embedding)."),
  nutriscore   STRING             OPTIONS(description="A | B | C | D | E. NULL si absent OFF."),
  nova         STRING             OPTIONS(description="1 | 2 | 3 | 4 (groupe NOVA, niveau de transformation)."),
  ecoscore     STRING             OPTIONS(description="A | B | C | D | E. NULL si absent OFF."),
  image_url    STRING             OPTIONS(description="URL de l'image principale OFF (front)."),
  off_found    BOOL      NOT NULL OPTIONS(description="False si l'EAN n'est pas dans OFF (404) — ligne quand même écrite pour ne pas re-tenter en boucle."),
  enriched_at  TIMESTAMP NOT NULL OPTIONS(description="UTC timestamp du run worker qui a écrit la ligne."),
  source       STRING    NOT NULL OPTIONS(description="Toujours `openfoodfacts` pour cette table.")
)
-- Pas de PARTITION BY : table de reference ~10^4-10^5 lignes, scan complet
-- cheap. Le clustering sur `ean` couvre les look-ups produit-par-produit.
CLUSTER BY ean
OPTIONS(
  description = "Catalogue produits enrichi via OFF — alimenté par worker-off (cron 04h UTC).",
  labels      = [("app", "price-tracker"), ("env", "prod"), ("managed_by", "terraform"), ("component", "silver")]
);
