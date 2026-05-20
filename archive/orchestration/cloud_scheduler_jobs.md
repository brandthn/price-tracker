Cloud Scheduler / Orchestration

- Ce projet utilise Cloud Scheduler + Cloud Run / Cloud Functions (pas Airflow).
- Exemples de jobs:
  - `ingestion-load-open-prices` -> déclenche `load_open_prices` (03:00)
  - `worker-off-enrichment` -> déclenche Worker OFF (04:00)
  - `worker-indices` -> déclenche Worker Indices (05:00)
- Chaque job peut publier un message Pub/Sub ou appeler une URL Cloud Run.
