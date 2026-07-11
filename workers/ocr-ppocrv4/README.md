# worker-ocr-ppocrv4

Worker OCR, backend **PP-OCRv4 mobile** (français, CPU) — variante rapide de
PaddleOCR : détection `PP-OCRv4_mobile_det` sous `paddle_static`, avec repli
automatique sur `paddle_dynamic`, et image redimensionnée à 640 px.

Un des 6 workers « un backend = un worker » issus de `dev_ocr`. Le pipeline
commun vit dans [`libs/pricetracker_receipt_pipeline`](../../libs/pricetracker_receipt_pipeline) ;
`ppocr_v4_backend.py` (et le `paddle_backend.py` qu'il enveloppe) sont propres à
ce worker.

## Flux

`Pub/Sub push (topic ocr-ppocrv4)` → `POST /push` (OIDC) → `tickets.gcs_path` →
image GCS → `PpOcrV4MobileBackend` (texte brut) → `ReceiptParser` →
`alias_lookup` (EAN) → écriture atomique `prix_extraits` + `tickets`.

Réponses : `204` = ACK (succès **ou** échec déterministe), `400` = payload
malformé (ACK), `5xx` = erreur transitoire → NACK → retry → DLQ après 5 essais.

## Modèles

Baked dans l'image au build (CDN Paddle, cf. `Dockerfile`) : le warm-up
instancie le vrai backend, donc le profil mobile **et** son fallback sont en
cache. Pas de téléchargement au cold start.

## Variables d'environnement

| Var | Défaut | Rôle |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | Projet GCP. |
| `PRT_OCR_ENGINE_LABEL` | `ppocrv4` | Écrit dans `tickets.ocr_engine` / `ocr_model`. |
| `RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE` | `640` | Redimensionnement avant OCR. |
| `RECEIPT_OCR_CPU_THREADS` | `2` | Plafond threads BLAS/OpenMP. |
| `PRT_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` / `POOL_SIZE` | — / 5432 / `price_tracker` / `pt_app` / — / 4 | Cloud SQL. `PASSWORD` = secret `prt-prod-cloudsql-password`. |
| `PRT_OIDC_DISABLE` | `0` | `1` = bypass OIDC (dev local uniquement). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | — | Allowlist des appelants. |
| `PRT_LOG_LEVEL` | `INFO` | |

## Développement

```bash
uv sync          # installe paddlepaddle (~100 Mo)
uv run pytest    # le backend est monkeypatché : Paddle n'est jamais chargé
```

## Build

Depuis la **racine du monorepo** :

```bash
docker build -f workers/ocr-ppocrv4/Dockerfile -t worker-ocr-ppocrv4:dev .
gcloud builds submit . --config=workers/ocr-ppocrv4/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD) \
  --project=price-tracker-prod-01
```

Déploiement : bumper `worker_ocr_ppocrv4_image_tag` dans
`infra/envs/prod/variables_ocr_backends.tf`, puis `terraform apply`.
