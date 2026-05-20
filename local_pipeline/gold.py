"""
Couche GOLD — Agrégation, indices et détection d'anomalies.

Objectif de la couche Gold :
    Produire des tables analytiques directement consommables par les
    dashboards, les alertes et les équipes métier. La Gold ne contient
    plus de lignes individuelles : ce sont des agrégats, des indicateurs
    et des signaux.

    En production, ces calculs tournent dans BigQuery via SQL. En local,
    on utilise DuckDB qui parle exactement le même dialecte SQL que BigQuery
    pour les fonctions fenêtrées (QUALIFY, LAG, PARTITION BY, etc.).
    La logique SQL est donc identique — seule la connexion change.

Les 4 tables Gold produites :

┌─────────────────────┬────────────────────────────────────────────────────┐
│ Table               │ Contenu                                            │
├─────────────────────┼────────────────────────────────────────────────────┤
│ aggregatsenseignes  │ Volume et prix médian par semaine/enseigne/pays    │
│ indicesinflation    │ Indice chaîné (base=100 première semaine)          │
│ rankingsproduits    │ Top 500 hausses de prix semaine sur semaine        │
│ anomaliesdetected   │ Lignes avec z-score ≥ 3 (σ) vs médiane historique │
└─────────────────────┴────────────────────────────────────────────────────┘

Pourquoi le z-score pour les anomalies ?
    Un z-score mesure combien de fois l'écart-type sépare un point de la
    moyenne. |z| ≥ 3 couvre 99.7% des cas normaux → seuls les vrais outliers
    sont signalés. C'est la détection d'anomalies la plus simple qui soit
    robuste aux distributions non-gaussiennes.

Pourquoi un indice chaîné (base 100) ?
    Exprimer les prix absolus n'est pas comparable entre enseignes ou entre
    produits. L'indice base 100 normalise : tout le monde part de 100 à la
    première semaine disponible, et on lit directement "+5 pts = +5%".
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import duckdb
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ──────────────────────────────────────────────────────────────────────────────
# Chemins locaux
# ──────────────────────────────────────────────────────────────────────────────

SILVER_CLEAN = _REPO_ROOT / "data" / "silver" / "openpricesclean.parquet"
GOLD_DIR     = _REPO_ROOT / "data" / "gold"

# Nombre minimum d'observations pour qu'un agrégat soit publié.
# En dessous de ce seuil, la médiane n'est pas statistiquement significative.
MIN_OBSERVATIONS = 3


# ──────────────────────────────────────────────────────────────────────────────
# Requêtes SQL Gold (DuckDB)
# ──────────────────────────────────────────────────────────────────────────────
# Note : ces requêtes sont la traduction directe des requêtes BigQuery du
# worker_indices/main.py. Le dialecte SQL est quasi-identique à deux nuances :
#   - BigQuery : APPROX_QUANTILES(x, 100)[OFFSET(50)]  → estimation probabiliste
#   - DuckDB   : MEDIAN(x)  → médiane exacte (possible en local car données <1M)
#   - BigQuery : DATE_SUB(DATE('...'), INTERVAL 12 WEEK)
#   - DuckDB   : DATE '...' - INTERVAL 12 WEEK
# En production on utilise APPROX_QUANTILES car le calcul exact sur 100M de
# lignes dans BigQuery serait trop coûteux. En local, MEDIAN() est exact.

def _sql_aggregats(run_date: str, min_obs: int) -> str:
    """
    Agrégats hebdomadaires par enseigne et pays.

    Pour chaque combinaison (semaine, enseigne, pays) on calcule :
    - observations : nombre de relevés de prix (proxy du volume)
    - avg_price_eur : prix moyen (sensible aux outliers, utile pour croiser)
    - median_price_eur : prix médian (robuste aux outliers, valeur de référence)

    La clause HAVING filtre les groupes trop petits pour être fiables.
    La fenêtre de 12 semaines limite la quantité de data recalculée à chaque run.
    """
    return f"""
    CREATE OR REPLACE TABLE aggregatsenseignes AS
    WITH base AS (
        SELECT
            week_start_date,
            store_brand,
            country_code,
            product_code,
            price_eur
        FROM silver
        WHERE week_start_date >= DATE '{run_date}' - INTERVAL 12 WEEK
          AND store_brand IS NOT NULL
    )
    SELECT
        week_start_date,
        store_brand,
        country_code,
        COUNT(*)                    AS observations,
        ROUND(AVG(price_eur), 4)    AS avg_price_eur,
        ROUND(MEDIAN(price_eur), 4) AS median_price_eur
    FROM base
    GROUP BY week_start_date, store_brand, country_code
    HAVING COUNT(*) >= {min_obs}
    ORDER BY week_start_date, store_brand
    """


def _sql_indices(run_date: str, min_obs: int) -> str:
    """
    Indice d'inflation chaîné, base 100 à la première semaine disponible.

    Algorithme en 3 étapes :
      1. med   : médiane hebdomadaire par enseigne/pays (même filtre que aggregats)
      2. bases : pour chaque enseigne/pays, on isole la première semaine disponible
                 (ROW_NUMBER() = 1 ORDER BY week_start_date) → c'est notre base 100
      3. JOIN  : on divise chaque médiane par la base × 100

    Exemple de lecture :
        store_brand="Carrefour", week="2026-03-02", index_value=103.5
        → Les prix Carrefour ont augmenté de 3.5% par rapport à la 1ère semaine observée.

    SAFE_DIVIDE protège contre la division par zéro (si base_price = 0).
    QUALIFY est une extension SQL supportée par DuckDB et BigQuery qui filtre
    sur les fonctions fenêtrées directement dans le SELECT (équivalent à un
    sous-SELECT avec WHERE sur le ROW_NUMBER).
    """
    return f"""
    CREATE OR REPLACE TABLE indicesinflation AS
    WITH med AS (
        SELECT
            week_start_date,
            store_brand,
            country_code,
            ROUND(MEDIAN(price_eur), 4) AS median_price_eur,
            COUNT(*)                     AS observations
        FROM silver
        WHERE week_start_date >= DATE '{run_date}' - INTERVAL 12 WEEK
          AND store_brand IS NOT NULL
        GROUP BY week_start_date, store_brand, country_code
        HAVING COUNT(*) >= {min_obs}
    ),
    bases AS (
        -- La première semaine par enseigne/pays devient la base de l'indice
        SELECT
            store_brand,
            country_code,
            median_price_eur AS base_price
        FROM med
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY store_brand, country_code
            ORDER BY week_start_date
        ) = 1
    )
    SELECT
        m.week_start_date,
        m.store_brand,
        m.country_code,
        m.observations,
        m.median_price_eur,
        b.base_price,
        CASE
            WHEN b.base_price IS NULL OR b.base_price = 0 THEN NULL
            ELSE ROUND(m.median_price_eur / b.base_price * 100, 2)
        END AS index_value
    FROM med m
    JOIN bases b USING (store_brand, country_code)
    ORDER BY m.store_brand, m.week_start_date
    """


def _sql_rankings(run_date: str, min_obs: int) -> str:
    """
    Top 500 produits ayant connu la plus forte hausse de prix d'une semaine à l'autre.

    Méthode :
      1. weekly  : médiane hebdomadaire par produit (sur 8 semaines)
      2. lagged  : LAG() amène la médiane de la semaine précédente
      3. pct_change = (prix_actuel - prix_précédent) / prix_précédent
      4. QUALIFY TOP 500 par ORDER BY pct_change DESC

    Cas limites gérés :
      - prev_median IS NULL : première semaine disponible, pas de comparaison possible
      - prev_median = 0 : prix nul (division par zéro) → pct_change = NULL
      → Les deux cas sont exclus du ranking

    En production, ce ranking alimente l'app mobile "Alertes Prix".
    """
    return f"""
    CREATE OR REPLACE TABLE rankingsproduits AS
    WITH weekly AS (
        SELECT
            week_start_date,
            product_code,
            ROUND(MEDIAN(price_eur), 4) AS median_price_eur,
            COUNT(*)                     AS observations
        FROM silver
        WHERE week_start_date >= DATE '{run_date}' - INTERVAL 8 WEEK
          AND product_code IS NOT NULL
        GROUP BY week_start_date, product_code
        HAVING COUNT(*) >= {min_obs}
    ),
    lagged AS (
        SELECT
            week_start_date,
            product_code,
            median_price_eur,
            LAG(median_price_eur) OVER (
                PARTITION BY product_code
                ORDER BY week_start_date
            ) AS prev_median
        FROM weekly
    )
    SELECT
        week_start_date   AS reference_week,
        product_code,
        prev_median,
        median_price_eur  AS curr_median,
        ROUND(
            CASE
                WHEN prev_median IS NULL OR prev_median = 0 THEN NULL
                ELSE (median_price_eur - prev_median) / prev_median
            END,
        4) AS pct_change
    FROM lagged
    WHERE prev_median IS NOT NULL AND prev_median > 0
    QUALIFY ROW_NUMBER() OVER (
        ORDER BY CASE
            WHEN prev_median = 0 THEN NULL
            ELSE (median_price_eur - prev_median) / prev_median
        END DESC NULLS LAST
    ) <= 500
    """


def _sql_anomalies(run_date: str, min_obs: int) -> str:
    """
    Détection d'anomalies par z-score sur les médianes hebdomadaires.

    Définition du z-score :
        z = (x - μ) / σ
        avec μ = moyenne des médianes sur toute la période
             σ = écart-type des médianes sur toute la période

    Seuil d'alerte : |z| ≥ 3
        Sous une distribution normale, seul 0.3% des points dépasse ce seuil.
        En pratique, un |z| ≥ 3 signale une semaine où le prix médian d'un
        produit dans une enseigne s'est très fortement écarté de son historique.

    Cas gérés :
        - std_med = NULL : produit avec une seule semaine de données (pas de variance)
        - std_med = 0    : prix parfaitement stable sur toute la période (z = ∞)
        Les deux cas sont exclus car non interprétables.

    En production, cette table alimente les alertes push "Prix anormal détecté".
    """
    return f"""
    CREATE OR REPLACE TABLE anomaliesdetected AS
    WITH weekly AS (
        SELECT
            week_start_date,
            product_code,
            store_brand,
            ROUND(MEDIAN(price_eur), 4) AS median_price_eur,
            COUNT(*)                     AS observations
        FROM silver
        WHERE week_start_date >= DATE '{run_date}' - INTERVAL 8 WEEK
          AND product_code IS NOT NULL
        GROUP BY week_start_date, product_code, store_brand
        HAVING COUNT(*) >= {min_obs}
    ),
    stats AS (
        SELECT
            week_start_date,
            product_code,
            store_brand,
            median_price_eur,
            observations,
            -- Moyenne et écart-type calculés sur TOUTE la fenêtre temporelle
            -- pour chaque couple (produit, enseigne) → fonctions fenêtrées
            ROUND(AVG(median_price_eur)    OVER w, 4) AS mean_med,
            ROUND(STDDEV_POP(median_price_eur) OVER w, 4) AS std_med
        FROM weekly
        WINDOW w AS (PARTITION BY product_code, store_brand)
    )
    SELECT
        week_start_date,
        product_code,
        store_brand,
        median_price_eur,
        observations,
        mean_med,
        std_med,
        ROUND(
            CASE
                WHEN std_med IS NULL OR std_med = 0 THEN NULL
                ELSE (median_price_eur - mean_med) / std_med
            END,
        3) AS z_score
    FROM stats
    WHERE std_med IS NOT NULL
      AND std_med > 0
      AND ABS(
            CASE
                WHEN std_med = 0 THEN NULL
                ELSE (median_price_eur - mean_med) / std_med
            END
          ) >= 3
    ORDER BY ABS(z_score) DESC NULLS LAST
    """


# ──────────────────────────────────────────────────────────────────────────────
# Fonction principale
# ──────────────────────────────────────────────────────────────────────────────

def run_gold(
    silver_path: Path | None = None,
    run_date: str | None = None,
    min_observations: int = MIN_OBSERVATIONS,
) -> Dict[str, Any]:
    """
    Exécute la couche Gold via DuckDB.

    DuckDB lit les Parquet Silver directement en mémoire (zero-copy via Arrow),
    exécute les 4 requêtes SQL, et persiste chaque résultat en Parquet Gold.

    Args:
        silver_path:      Chemin vers openpricesclean.parquet (défaut : SILVER_CLEAN)
        run_date:         Date de référence au format YYYY-MM-DD (défaut : aujourd'hui)
        min_observations: Taille min d'un groupe pour être agrégé (défaut : 3)

    Returns:
        Métriques de la couche Gold (nombre de lignes par table, etc.)
    """
    silver_path = silver_path or SILVER_CLEAN
    run_date    = run_date or datetime.now(timezone.utc).date().isoformat()
    GOLD_DIR.mkdir(parents=True, exist_ok=True)

    print("\n" + "═" * 60)
    print("  GOLD — Agrégation & signaux analytiques")
    print("═" * 60)
    print(f"  [Gold] Source Silver  : {silver_path}")
    print(f"  [Gold] Date de run    : {run_date}")
    print(f"  [Gold] Min obs/groupe : {min_observations}")

    # ── Connexion DuckDB en mémoire ───────────────────────────────────────────
    # DuckDB in-process : pas de serveur, pas de port, parfait pour le local.
    # Il charge le Parquet via Arrow Zero-Copy : très rapide même sur 1M lignes.
    con = duckdb.connect()

    # On crée une vue "silver" en castant les dates VARCHAR → DATE.
    # Le cleaner stocke week_start_date et price_date en string ISO 8601
    # (ex: "2026-05-12"). DuckDB ne peut pas comparer VARCHAR avec DATE '...'
    # sans cast explicite. On le fait ici une seule fois pour tous les SQL Gold.
    # store_brand_normalized est utilisé pour agréger par enseigne (pas l'adresse OSM brute).
    con.execute(f"""
        CREATE VIEW silver AS
        SELECT
            id, product_code, price_eur, currency, proof_type,
            country_code, store_brand_normalized AS store_brand,
            location_id, location_name,
            city, postcode, source, ingested_at,
            CAST(price_date      AS DATE) AS price_date,
            CAST(week_start_date AS DATE) AS week_start_date
        FROM read_parquet('{silver_path}')
    """)

    # ── Exécution des 4 requêtes Gold ─────────────────────────────────────────
    gold_tables = {
        "aggregatsenseignes": _sql_aggregats(run_date, min_observations),
        "indicesinflation":   _sql_indices(run_date, min_observations),
        "rankingsproduits":   _sql_rankings(run_date, min_observations),
        "anomaliesdetected":  _sql_anomalies(run_date, min_observations),
    }

    metrics: Dict[str, Any] = {
        "run_date":   run_date,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tables":     {},
    }

    for table_name, sql in gold_tables.items():
        print(f"\n  [Gold] Calcul de '{table_name}'…")

        # Exécution SQL dans DuckDB (crée la table en mémoire)
        con.execute(sql)

        # Lecture du résultat pour export + comptage
        df = con.execute(f"SELECT * FROM {table_name}").df()
        n_rows = len(df)

        # Export Parquet Gold
        out_path = GOLD_DIR / f"{table_name}.parquet"
        df.to_parquet(out_path, index=False, engine="pyarrow")

        metrics["tables"][table_name] = {
            "n_rows":    n_rows,
            "columns":   list(df.columns),
            "parquet":   str(out_path),
        }
        print(f"  [Gold] {table_name:<22} → {n_rows:>6,} lignes  ({out_path.name})")

    con.close()

    metrics["finished_at"] = datetime.now(timezone.utc).isoformat()

    # ── Aperçu des tables Gold ────────────────────────────────────────────────
    _print_gold_previews()

    return metrics


def _print_gold_previews() -> None:
    """Affiche un aperçu de chaque table Gold pour un retour immédiat."""
    import textwrap

    previews = {
        "aggregatsenseignes": "Agrégats hebdomadaires (5 premières lignes)",
        "indicesinflation":   "Indice inflation (5 premières lignes)",
        "rankingsproduits":   "Top hausses de prix (5 premières)",
        "anomaliesdetected":  "Anomalies détectées (toutes)",
    }

    for table, label in previews.items():
        path = GOLD_DIR / f"{table}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty:
            print(f"\n  [{table}] Aucune ligne (données insuffisantes pour ce seuil)")
            continue
        print(f"\n  ── {label} ──")
        with pd.option_context("display.max_columns", 10, "display.width", 120):
            print(textwrap.indent(str(df.head(5)), "  "))
