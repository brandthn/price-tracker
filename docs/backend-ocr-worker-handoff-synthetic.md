Here's a condensed, action-oriented version:

---

# OCR Worker — Go-Live Handoff

## What's the situation

The OCR pipeline is almost entirely built. One thing is missing at each layer:

| Layer | Blocker |
|-------|---------|
| Cloud Run `prt-prod-worker-ocr` | Still running a skeleton image — no real OCR happens |
| Cloud SQL | `tickets` / `prix_extraits` tables don't exist yet |
| Backend | Upload API not implemented |

**Everything else** (GCS bucket, Pub/Sub, IAM, notifications) is already provisioned.

---

## How it works (the flow you're building toward)

```
App → POST /tickets/upload-url → Backend creates DB row + returns signed URL
App → PUT image → GCS
GCS → Pub/Sub → Worker → Groq OCR → Cloud SQL
App → GET /tickets/{id} → polls until ocr_done
```

The worker **never creates** the `tickets` row — backend must do that **before** the client uploads. If the row doesn't exist when the image lands, OCR silently does nothing.

---

## What backend needs to do

### 1. Run Alembic migrations (do this first, before the worker goes live)

Three objects to create:

**`ticket_status` enum** — values: `pending`, `uploaded`, `ocr_processing`, `ocr_done`, `ocr_failed`, `validated`

**`tickets` table** — key columns: `id uuid PK`, `user_id uuid FK→users`, `gcs_object_path text UNIQUE`, `status ticket_status DEFAULT 'pending'`, plus OCR output columns (`enseigne`, `ticket_date`, `total_amount`, `ocr_confidence`, `ocr_engine`, `error_message`, …)

**`prix_extraits` table** — PK is `(ticket_id, line_index)`, columns: `raw_text`, `quantity`, `unit_price`, `line_total`, `ean` (always NULL now), `needs_validation` (always TRUE now)

Full DDL is in §4 of the original doc.

### 2. Implement three API endpoints

**`POST /tickets/upload-url`** — the critical one. Order of operations matters:
1. Resolve `user_id` from JWT
2. Generate `ticket_id = uuid4()`
3. Build path: `tickets/raw/{user_id}/{ticket_id}.{ext}`
4. `INSERT INTO tickets` with `status = 'pending'` ← **must happen before returning the URL**
5. Generate V4 signed PUT URL (15 min TTL)
6. Return `ticket_id`, `upload_url`, `gcs_object_path`

**`GET /tickets/{ticket_id}`** — return status + OCR output fields. Frontend polls this.

**`GET /tickets/{ticket_id}/lines`** — return `prix_extraits` rows ordered by `line_index`.

**`POST /tickets/{ticket_id}/validate`** — set `validated_by_user = true` on lines, set ticket status to `validated`.

### 3. GCS path convention — get this exactly right

The worker parses `ticket_id` from the path with a regex. Use exactly:

```
tickets/raw/{user_id}/{ticket_id}.jpg
```

Anything else (wrong prefix, missing `raw/`, wrong UUID position) → worker silently skips or errors.

---

## What platform/DevOps needs to do

**Do this after** backend migrations are applied.

### 1. Build and push the image

```bash
export PROJECT_ID=price-tracker-prod-01
export SHORT_SHA=$(git rev-parse --short HEAD)
gcloud builds submit . --project="$PROJECT_ID" \
  --config=workers/ocr/cloudbuild.yaml \
  --substitutions=_SHORT_SHA="$SHORT_SHA"
```

Build context must be **monorepo root**, not `workers/ocr/`.

### 2. Add the Groq API key to Secret Manager

```bash
# After terraform creates the secret:
echo -n "YOUR_GROQ_API_KEY" | gcloud secrets versions add prt-prod-groq-api-key \
  --project=price-tracker-prod-01 --data-file=-
```

Add `"${var.name_prefix}-groq-api-key"` to `secret_manager.tf` with `accessors = [local.worker_sa]`.

### 3. Update `cloud_run.tf` — replace the skeleton

In `infra/envs/prod/cloud_run.tf`, the `run_worker_ocr` module currently points to a placeholder image. Replace it to mirror `run_worker_off`, with:
- `image` pointing to the real Artifact Registry image + `var.worker_ocr_image_tag`
- `timeout_seconds = 540` (must be under the Pub/Sub ack deadline of 600s)
- `memory = "1Gi"`, `max_instances = 5`
- All `PRT_*` env vars: `GOOGLE_CLOUD_PROJECT`, `PRT_BRONZE_BUCKET`, `PRT_OCR_ENGINE=groq`, `PRT_PG_*` connection settings, `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS`
- Secrets: `PRT_PG_PASSWORD` and `GROQ_API_KEY`

Add `variable "worker_ocr_image_tag"` to `variables.tf`.

### 4. Apply and verify

```bash
terraform apply
# Then check health:
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "{SERVICE_URL}/healthz"
# Expected: {"status":"ok"}
```

---

## Deployment order

| Step | Who | What |
|------|-----|------|
| 1 | Backend | Alembic migrations on prod |
| 2 | Backend | Upload APIs on staging |
| 3 | Platform | Build + push image |
| 4 | Platform | Terraform apply (secret + env + image swap) |
| 5 | Platform | Populate Groq secret version |
| 6 | QA | E2E test with a real receipt image |

---

## How to know it's working

After a test upload, check:
```sql
SELECT status, enseigne, ticket_date, total_amount FROM tickets WHERE id = '<id>';
SELECT line_index, raw_text, unit_price FROM prix_extraits WHERE ticket_id = '<id>';
```

In Cloud Logging, look for structured events: `push_received` → `ocr_start` → `ocr_done` → `pg_upsert_done`.

---

## Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ocr_done` but no lines | Receipt image unreadable | Check Groq response in logs |
| Status stuck at `pending` | Row missing or path mismatch | Verify INSERT happens before PUT; check path format |
| Worker 5xx loop in Pub/Sub | Missing env vars or DB unreachable | Check `PRT_PG_*` and secrets |
| `ocr_failed` every time | Bad `GROQ_API_KEY` | Verify secret version |
| Silent 204, no OCR | Ticket row missing or wrong status | Backend must INSERT before client uploads |