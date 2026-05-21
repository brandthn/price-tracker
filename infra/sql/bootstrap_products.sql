-- Bootstrap one-shot Phase 6.2 : table Cloud SQL `products` (pgvector dim 768).
--
-- À exécuter UNE FOIS après `terraform apply` Phase 4 + bootstrap_pgvector.sql,
-- AVANT le premier run du worker OFF (Phase 6.2). Connexion via Cloud SQL
-- Studio ou Cloud SQL Auth Proxy avec l'utilisateur `pt_app` (cf. runbook
-- `infra/README.md` §"Bootstrap pgvector"). Identique en pratique.
--
-- Idempotent (IF NOT EXISTS). Pourquoi pas une migration Alembic ? Alembic
-- arrivera en Phase 7 avec le backend FastAPI ; on bootstrap minimal ici
-- pour que worker-off (Phase 6.2) puisse écrire sans attendre. Alembic
-- récupèrera ce schéma comme baseline via `alembic stamp head`.
--
-- Schéma aligné avec :
--   - `prt_prod_silver.catalogue_produits` (BQ — colonnes communes en double-write)
--   - `workers/off/src/pricetracker_off/pg.py` (requête UPSERT)

-- Prérequis : pgvector déjà installée (cf. bootstrap_pgvector.sql)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS products (
    ean           text         PRIMARY KEY,
    name          text,
    brand         text,
    category_l1   text,
    category_l2   text,
    category_l3   text,
    nutriscore    text,
    nova          text,
    ecoscore      text,
    image_url     text,
    off_found     boolean      NOT NULL DEFAULT false,
    embedding     vector(768),         -- NULL si EAN absent de OFF (pas d'input texte)
    enriched_at   timestamptz  NOT NULL DEFAULT now(),
    source        text         NOT NULL DEFAULT 'openfoodfacts'
);

-- Index HNSW pour la recherche par similarité cosinus (substituts produit,
-- Phase 8 worker-ocr + Phase 7 backend `GET /products/{ean}/substitutes`).
-- HNSW > IVFFlat sur petites tables (<100k rows) avec recall/perf supérieurs.
-- Cosine ops : on compare des embeddings normalisés de `text-embedding-004`.
CREATE INDEX IF NOT EXISTS products_embedding_hnsw_cos
    ON products USING hnsw (embedding vector_cosine_ops);

-- Index secondaires courants côté backend Phase 7.
CREATE INDEX IF NOT EXISTS products_brand_idx ON products (brand);
CREATE INDEX IF NOT EXISTS products_category_l3_idx ON products (category_l3);

-- Vérification : doit afficher la table avec 14 colonnes.
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'products'
ORDER BY ordinal_position;
