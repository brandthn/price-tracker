-- FICHIER : transform/models/dim/dim_location.sql
-- RÔLE    : Créer la table de dimension des localisations (magasins)
--
-- Cette table répond à la question : "Dans quel magasin ce prix a-t-il été relevé ?"
-- On déduplique : chaque location_id n'apparaît qu'une seule fois.
--
-- {{ source('raw', 'open_prices') }} est la syntaxe dbt pour référencer
-- notre fichier Parquet brut déclaré dans sources.yml

{{ config(materialized='table') }}

WITH prix_bruts AS (
    -- On part de la source brute
    SELECT * FROM {{ source('raw', 'open_prices') }}
),

locations_uniques AS (
    -- On garde UNE SEULE ligne par location_id
    -- ROW_NUMBER() numérote les doublons : on garde seulement le n°1
    SELECT
        location_id,
        location_osm_display_name   AS display_name,
        location_osm_address_city   AS city,
        location_osm_address_postcode AS postcode,
        location_osm_address_country  AS country,
        location_osm_lat            AS latitude,
        location_osm_lon            AS longitude,

        -- On classe les doublons par location_id
        -- pour ne garder qu'un seul enregistrement par magasin
        ROW_NUMBER() OVER (
            PARTITION BY location_id
            ORDER BY location_id
        ) AS rang

    FROM prix_bruts
    WHERE location_id IS NOT NULL  -- on exclut les prix sans localisation connue
)

-- Résultat final : uniquement les lignes de rang 1 (pas de doublons)
SELECT
    location_id,
    display_name,
    city,
    postcode,
    country,
    latitude,
    longitude
FROM locations_uniques
WHERE rang = 1