-- FICHIER : transform/models/fact/fact_price.sql
-- RÔLE    : Créer la table de faits centrale FACT_PRICE
--
-- C'est la table la plus importante du projet.
-- Elle contient TOUS les prix observés, avec les clés étrangères
-- qui pointent vers chaque dimension.
--
-- INCREMENTAL = dbt n'ajoute que les nouvelles lignes à chaque exécution.
-- Cela évite de tout recalculer chaque jour.

{{
    config(
        materialized='incremental',
        unique_key='price_id'    -- si un price_id existe déjà, on le met à jour
    )
}}

WITH source AS (
    SELECT * FROM {{ source('raw', 'open_prices') }}
),

prix_enrichis AS (
    SELECT
        -- Identifiant unique de chaque observation de prix
        s.id                            AS price_id,

        -- Clés étrangères vers les tables de dimension
        -- (les JOIN permettent de récupérer les IDs propres)
        prod.product_id,
        loc.location_id,
        dat.date_id,
        cur.currency_id,

        -- Mesures : les vraies valeurs numériques
        CAST(s.price AS DECIMAL(10, 3))                     AS price,
        s.price_is_discounted,
        CAST(s.price_without_discount AS DECIMAL(10, 3))    AS price_without_discount,
        s.price_per,        -- KILOGRAM ou UNIT
        s.proof_type,       -- RECEIPT, PRICE_TAG...

        -- Date de création pour le mode incrémental
        s.date AS observation_date

    FROM source s

    -- Jointure avec la dimension produit
    LEFT JOIN {{ ref('dim_product') }}  prod ON s.product_code = prod.product_code

    -- Jointure avec la dimension localisation
    LEFT JOIN {{ ref('dim_location') }} loc  ON s.location_id  = loc.location_id

    -- Jointure avec la dimension date
    LEFT JOIN {{ ref('dim_date') }}     dat  ON s.date          = dat.date

    -- Jointure avec la dimension devise
    LEFT JOIN {{ ref('dim_currency') }} cur  ON s.currency      = cur.currency_code

    -- Filtre qualité : on refuse les prix négatifs ou aberrants
    WHERE CAST(s.price AS DECIMAL(10,3)) > 0
      AND CAST(s.price AS DECIMAL(10,3)) < 10000
)

SELECT * FROM prix_enrichis

-- MODE INCREMENTAL : si ce n'est pas la première exécution,
-- on n'insère que les lignes plus récentes que ce qu'on a déjà
{% if is_incremental() %}
WHERE observation_date > (SELECT MAX(observation_date) FROM {{ this }})
{% endif %}