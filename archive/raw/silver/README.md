Silver (clean):

- Emplacement: BigQuery dataset `silver` (table `open_prices_clean`, `catalogue_produits`).
- Contenu: données filtrées, dédupliquées, normalisées, partitionnées par date.
- Alimenté par: Worker Ingestion (ex: 03:00), chargement depuis GCS Bronze -> Parquet -> BigQuery.
