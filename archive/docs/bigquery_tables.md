BigQuery tables (extrait)

DATASET: silver

- `open_prices_clean` : Toutes les entrées Open Prices filtrées France, dédupliquées par id, partitionné par date. Alimenté par Worker Ingestion (03:00) depuis GCS Bronze Parquet -> BQ.
- `catalogue_produits` : Une ligne par EAN : nom, marque, catégorie L1/L2/L3, nutriscore, unité référence. Alimenté par Worker OFF (04:00) qui appelle OFF API pour enrichir.

DATASET: gold

- `indices_inflation` : Indices Laspeyres (national, régional, par catégorie COICOP) vs INSEE. Calculé par Worker Indices (05:00) à partir de `silver.open_prices_clean` et `silver.catalogue_produits`.
- `aggregats_enseignes` : Prix moyen par produit × enseigne × semaine. Agrégation SQL depuis `open_prices_clean`.
- `rankings_produits` : Top hausses du mois, Hall of Shame.
- `anomalies_detected` : Prix flaggés Z-score > seuil, exclus des calculs d'indices.

KPIs & sorties modèles:
- Stocker les métriques qualité OCR (taux de reconnaissance, confidence) dans `silver` puis agrégations en `gold`.
- Exposer via API et rapports (BigQuery -> Looker Studio / CSV exports).
