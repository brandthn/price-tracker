# worker-ocr

Cloud Run worker OCR — déclenché par Pub/Sub `ticket-uploaded`.

## Pipeline

```
POST /push  ← Pub/Sub push (OIDC)
  ├─ parse envelope → (bucket, gcs_object_path)
  ├─ derive ticket_id (UUID dans le nom de fichier GCS)
  ├─ UPDATE tickets SET status='ocr_processing' (idempotent)
  ├─ download image GCS
  ├─ OCR (receipt_ocr / Groq LLaMA 4 Scout)
  ├─ mapper → ticket_fields + prix_extraits rows
  ├─ UPDATE tickets SET status='ocr_done' + champs OCR
  └─ INSERT prix_extraits (ON CONFLICT (ticket_id, line_index) DO UPDATE)
```

## Build (depuis la racine du monorepo)

```bash
SHORT_SHA=$(git rev-parse --short HEAD)
gcloud builds submit . \
  --config=workers/ocr/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=${SHORT_SHA} \
  --project=price-tracker-prod-01
```

## Tests unitaires

```bash
cd workers/ocr
uv sync --group dev
uv run pytest -m "not integration"
```

## Variables d'environnement

| Variable | Description |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Projet GCP |
| `PRT_BRONZE_BUCKET` | Bucket GCS bronze |
| `PRT_OCR_ENGINE` | `groq` \| `paddleocr` \| `tesseract` |
| `PRT_PG_HOST` / `_PORT` / `_DB` / `_USER` / `_PASSWORD` | Cloud SQL |
| `GROQ_API_KEY` | Clé API Groq (secret Manager) |
| `PRT_OIDC_DISABLE` | `1` en dev uniquement |
