# pricetracker-indices

Worker Phase 9.1 — recalcule les agrégats Gold à partir de Silver
(`open_prices_clean`) :

- `aggregats_enseignes` : volume + prix moyen/médian par semaine × enseigne × pays (12 semaines).
- `indices_inflation` : indice chaîné base 100 sur la médiane hebdomadaire (12 semaines).
- `rankings_produits` : top 500 hausses semaine sur semaine (8 semaines).
- `anomalies_detected` : prix médians avec |z-score| ≥ 3 vs historique (8 semaines).

Déclenché par Cloud Scheduler `prt-prod-trigger-indices` (cron 05h UTC) via POST /run + OIDC.

## Run local

```bash
uv sync
uv run uvicorn pricetracker_indices.main:app --reload --port 8080
```

`PRT_OIDC_DISABLE=1` pour bypasser la vérification OIDC en dev.
