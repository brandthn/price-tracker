-- FICHIER : serving/schema.sql
-- RÔLE    : Créer le schéma en étoile dans PostgreSQL
--
-- Ce script est exécuté automatiquement par Docker au premier démarrage.
-- Il crée toutes les tables vides que dbt va ensuite remplir.

-- ─── Schéma dédié pour isoler nos tables ──────────────────────────────────
CREATE SCHEMA IF NOT EXISTS pricetracker;

-- ─── DIM_DATE ──────────────────────────────────────────────────────────────
-- Toutes les dates possibles, pré-calculées.
-- Permet de filtrer facilement par mois, trimestre, année.
CREATE TABLE IF NOT EXISTS pricetracker.dim_date (
    date_id     SERIAL PRIMARY KEY,
    date        DATE        NOT NULL UNIQUE,
    day         SMALLINT    NOT NULL,   -- 1 à 31
    month       SMALLINT    NOT NULL,   -- 1 à 12
    year        SMALLINT    NOT NULL,   -- 2020, 2021...
    quarter     SMALLINT    NOT NULL,   -- 1 à 4
    week        SMALLINT    NOT NULL,   -- semaine ISO (1 à 53)
    is_weekend  BOOLEAN     NOT NULL    -- TRUE si samedi ou dimanche
);

-- ─── DIM_PRODUCT ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pricetracker.dim_product (
    product_id      SERIAL PRIMARY KEY,
    product_code    VARCHAR(50),        -- code-barres EAN
    product_name    VARCHAR(500),       -- nom du produit
    category_tag    VARCHAR(200),       -- catégorie Open Food Facts
    labels_tags     TEXT                -- labels (bio, AOP, etc.)
);

-- ─── DIM_LOCATION ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pricetracker.dim_location (
    location_id     INTEGER PRIMARY KEY,
    display_name    VARCHAR(500),
    city            VARCHAR(200),
    postcode        VARCHAR(20),
    country         VARCHAR(100),
    latitude        DECIMAL(10, 7),
    longitude       DECIMAL(10, 7)
);

-- ─── DIM_CURRENCY ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pricetracker.dim_currency (
    currency_id     SERIAL PRIMARY KEY,
    currency_code   CHAR(3) NOT NULL UNIQUE,   -- EUR, CHF, USD...
    currency_name   VARCHAR(100)
);

-- ─── FACT_PRICE : table centrale ───────────────────────────────────────────
-- Contient tous les prix observés.
-- Chaque ligne = un prix relevé à un endroit, une date, pour un produit.
CREATE TABLE IF NOT EXISTS pricetracker.fact_price (
    price_id                INTEGER PRIMARY KEY,
    product_id              INTEGER REFERENCES pricetracker.dim_product(product_id),
    location_id             INTEGER REFERENCES pricetracker.dim_location(location_id),
    date_id                 INTEGER REFERENCES pricetracker.dim_date(date_id),
    currency_id             INTEGER REFERENCES pricetracker.dim_currency(currency_id),
    price                   DECIMAL(10, 3) NOT NULL,
    price_is_discounted     BOOLEAN DEFAULT FALSE,
    price_without_discount  DECIMAL(10, 3),
    price_per               VARCHAR(20),    -- KILOGRAM ou UNIT
    proof_type              VARCHAR(50),    -- RECEIPT, PRICE_TAG...
    observation_date        DATE NOT NULL,

    -- Index sur les colonnes les plus utilisées dans les filtres
    -- Accélère fortement les requêtes analytiques
    CONSTRAINT prix_positif CHECK (price > 0)
);

CREATE INDEX idx_fact_price_date     ON pricetracker.fact_price(observation_date);
CREATE INDEX idx_fact_price_location ON pricetracker.fact_price(location_id);
CREATE INDEX idx_fact_price_product  ON pricetracker.fact_price(product_id);