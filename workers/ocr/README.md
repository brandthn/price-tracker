# worker-ocr

Cloud Run worker `prt-prod-worker-ocr`: Pub/Sub push → GCS image → `receipt_ocr` (Groq VLM) → Cloud SQL.

## Local development

```bash
cd workers/ocr
uv sync
export PRT_OIDC_DISABLE=1
export PYTHONPATH=../../dev_ocr/src  # if receipt-ocr not installed via uv
pytest
```

## Docker build

Build from **monorepo root** (needs `dev_ocr/src` for `receipt_ocr`):

```bash
docker build -f workers/ocr/Dockerfile -t worker-ocr:local .
```

## Cloud Build

Submit from monorepo root:

```bash
gcloud builds submit . --config=workers/ocr/cloudbuild.yaml --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD)
```
