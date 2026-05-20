-- FICHIER : transform/models/mart/mart_inflation_par_ville.sql
-- RÔLE    : Vue analytique principale pour le dashboard
--
-- Cette vue calcule l'évolution mensuelle des prix par ville et par catégorie.
-- C'est ce que Metabase utilisera pour afficher les graphiques d'inflation.
--
-- Un "mart" (data mart) est une vue pré-calculée optimisée pour un cas d'usage précis.

{{ config(materialized='view') }}

WITH prix_mensuels AS (
    SELECT
        -- On regroupe par mois (format YYYY-MM)
        DATE_TRUNC('month', fp.observation_date)    AS mois,
        dl.city                                      AS ville,
        dl.country                                   AS pays,
        dp.category_tag                              AS categorie,

        -- Prix moyen du mois pour ce groupe
        ROUND(AVG(fp.price), 3)                      AS prix_moyen,

        -- Nombre d'observations (plus il y en a, plus la moyenne est fiable)
        COUNT(*)                                     AS nb_observations

    FROM {{ ref('fact_price') }} fp

    -- On récupère la ville depuis la dimension localisation
    LEFT JOIN {{ ref('dim_location') }} dl ON fp.location_id = dl.location_id

    -- On récupère la catégorie depuis la dimension produit
    LEFT JOIN {{ ref('dim_product') }}  dp ON fp.product_id  = dp.product_id

    -- On se concentre sur les prix en euros pour simplifier
    WHERE fp.price_is_discounted = FALSE   -- on exclut les promos
      AND dl.country = 'France'            -- focus France

    GROUP BY 1, 2, 3, 4
),

-- On calcule l'évolution vs le mois précédent (LAG = valeur précédente)
evolution AS (
    SELECT
        *,
        LAG(prix_moyen) OVER (
            PARTITION BY ville, categorie   -- on compare dans le même groupe
            ORDER BY mois
        ) AS prix_mois_precedent,

        -- Calcul du taux d'inflation mensuel en %
        ROUND(
            (prix_moyen - LAG(prix_moyen) OVER (
                PARTITION BY ville, categorie ORDER BY mois
            )) / NULLIF(LAG(prix_moyen) OVER (
                PARTITION BY ville, categorie ORDER BY mois
            ), 0) * 100,
            2
        ) AS evolution_pct

    FROM prix_mensuels
    WHERE nb_observations >= 5  -- on exige au moins 5 observations pour être fiable
)

SELECT * FROM evolution
ORDER BY mois DESC, ville, categorie