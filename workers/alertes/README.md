# pricetracker-alertes

Worker Phase 9.2 — V1 simulation. Lit BQ Gold (`rankings_produits` +
`anomalies_detected`), agrège les signaux de hausse, et écrit un rapport JSON
dans `gs://price-tracker-prod-01-bronze/alerts/date=YYYY-MM-DD/report.json`.

**Pas de FCM push** dans cette V1 : pas d'app mobile, pas de device tokens
disponibles. Le rapport JSON pourra être consommé par un endpoint backend
(`GET /alerts/latest`) ou un envoi email batch en Phase 11.

Déclenché par Cloud Scheduler `prt-prod-trigger-alertes` (cron 07h UTC) via
POST /run + OIDC.

## Run local

```bash
uv sync
uv run uvicorn pricetracker_alertes.main:app --reload --port 8080
```

`PRT_OIDC_DISABLE=1` pour bypasser la vérification OIDC en dev.
