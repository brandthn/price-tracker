# Deploying the receipt VLM in the GCP OCR worker — plan

**Status:** proposal, for team review · **Date:** 2026-06-18

## Context

We trained a hybrid receipt VLM (`receipt-vlm-500m`) and produced a merged inference checkpoint
(`receipt_vlm_500m_merged.pt`, ~1.8 GB). We want the **deployed GCP OCR worker** to be able to run
it. The VLM is already integrated into the `receipt_ocr` *library* (provider
`receipt_ocr.backends.vlm.receipt_vlm_provider.ReceiptVlmProvider`, selected by env vars), but the
**deployed worker (`prt-prod-worker-ocr`) cannot use it** — it is wired and resourced for Groq only.

Chosen shape (to revisit with the team):
- **Run the VLM inside the existing OCR worker** (not a separate service).
- **GPU (NVIDIA L4)** for inference.
- **Opt-in / experimental** — Groq stays the production default; the VLM is selectable.

The clean way to honor "in-worker + opt-in + GPU" without paying for a GPU on the default Groq path
is a **Terraform toggle** (`ocr_vlm_enabled`): when off, the worker is today's lean CPU/Groq service;
when on, the same image is deployed with an L4 GPU, more memory, the model mounted, and
`PRT_OCR_ENGINE=receipt-vlm-500m`. Flip it on to demo/evaluate, off to go back to Groq.

> Alternative considered: a **separate self-hosted inference service** the worker calls over HTTP
> (same pattern as Groq today). Cleaner separation and independent scaling/GPU, but more infra. We
> chose in-worker for directness; noted here in case the team prefers it.

## Readiness assessment — what's missing today

| Area | State today | Gap to close |
|---|---|---|
| Library provider | ✅ `ReceiptVlmProvider` loads from `RECEIPT_VLM_MODEL_PATH`, JSON-only | none |
| Worker engine wiring | ❌ `ocr.py::_configure_engine` only knows `groq`/`paddleocr`/`tesseract` | add a `receipt-vlm-500m` branch |
| Worker dependencies | ❌ image installs only base `receipt-ocr` (no torch/transformers/`receipt_vlm`) | add CUDA torch + transformers + the `receipt_vlm` package |
| Model file | ❌ 1.8 GB `.pt` is gitignored, not in GCS, not in image | upload to the `*-models` bucket, mount into the container |
| HF backbones at load | ⚠️ model construction pulls CLIP + SmolLM2 from HF Hub at cold start | bake the HF cache into the image + offline env vars |
| Compute sizing | ❌ 2Gi / 2 vCPU / CPU-only, sized for Groq ("aucune inférence locale") | L4 GPU + ≥16Gi / ≥4 vCPU (Cloud Run GPU minimums) |
| Terraform module | ❌ `modules/cloud_run` has no GPU or volume support; hardcodes `cpu_idle=true` | extend module for GPU + GCS volume |
| Repo hygiene | ❌ unresolved merge-conflict markers in worker `Dockerfile`, `config.py`, `pyproject.toml` | resolve before any build |

**Short answer to "is it ready?": no.** The model and library integration are done; the *deployed
worker* needs work across code, deps, model distribution, HF cache, GPU sizing, and Terraform — plus
the merge conflicts must be resolved before anything builds.

## Plan & steps

### 0. Prerequisite — resolve the merge conflicts
`workers/ocr/Dockerfile`, `workers/ocr/pyproject.toml`, `workers/ocr/pricetracker_ocr/config.py` all
contain `<<<<<<< HEAD` markers. The image cannot build until these are resolved. Pick the intended
side for each (the `origin` side copies `dev_ocr` to `/app/dev_ocr` and keeps `receipt-ocr` editable;
confirm which is canonical) and remove the markers.

### 1. Worker engine wiring (small code change)
- `workers/ocr/pricetracker_ocr/ocr.py` — add a branch to `_configure_engine()` for
  `receipt-vlm-500m` (mirror the existing `groq` branch): set `RECEIPT_OCR_BACKEND=vlm`,
  `RECEIPT_VLM_MODEL=receipt-vlm-500m` (`VlmModelName.RECEIPT_VLM_500M`), `RECEIPT_VLM_MODE=json`,
  and `RECEIPT_VLM_MODEL_PATH` from settings. Reuse the **already-declared-but-unused**
  `prt_ocr_model_uri` field in `config.py` as the local mounted checkpoint path.

### 2. Worker dependencies + Dockerfile
- `workers/ocr/pyproject.toml` — add an optional dependency group (e.g. `vlm`) with the inference
  deps from `dev_ocr/requirements-receipt-vlm.txt` (`transformers`, `tokenizers`, `Pillow`, `numpy`)
  plus **CUDA torch** (e.g. `torch==2.4.* cu121` via a `[tool.uv.sources]`/index entry — not the
  default CPU wheel) and the `receipt_vlm` package (`dev_ocr/vlm_training`, currently only importable,
  not a dep).
- `workers/ocr/Dockerfile` — for the VLM image:
  - `uv sync` including the `vlm` group;
  - **bake the HF cache**: a build step running `from_pretrained("openai/clip-vit-base-patch16")` and
    `from_pretrained("HuggingFaceTB/SmolLM2-360M-Instruct")` into a baked `HF_HOME` (e.g.
    `/opt/hf-cache`); set runtime `HF_HOME=/opt/hf-cache`, `HF_HUB_OFFLINE=1`,
    `TRANSFORMERS_OFFLINE=1` so cold start never hits HF Hub. (Model ids: `CLIP_MODEL`, `LM_MODEL` in
    `dev_ocr/vlm_training/receipt_vlm/models/vlm.py`.)
- Note: Cloud Run provides the NVIDIA driver; the cuXXX torch wheel bundles CUDA libs, so the
  `python:3.11-slim` base works without a full CUDA base image (add `libgomp1` if torch complains).

### 3. Model distribution (GCS volume mount)
- Upload the merged checkpoint:
  `gsutil cp receipt_vlm_500m_merged.pt gs://price-tracker-prod-01-models/ocr/v1/`
  (bucket `price-tracker-prod-01-models` already exists, `worker-sa` has `objectViewer`).
- Mount that bucket as a **Cloud Run GCS volume** at `/models`, and set
  `prt_ocr_model_uri = /models/ocr/v1/receipt_vlm_500m_merged.pt`. (Volume mount avoids baking 1.8 GB
  into the image and re-uploading on every build.)

### 4. Terraform — GPU + volume + sizing (bulk of the infra work)
- `infra/modules/cloud_run/{main,variables}.tf` — extend to support:
  - GPU: `resources.limits["nvidia.com/gpu"]`, `node_selector { accelerator = "nvidia-l4" }`,
    and `gpu_zonal_redundancy_disabled` (true to cut cost); make `cpu_idle` configurable.
  - GCS volume: `template.volumes { gcs { bucket } }` + `volume_mounts`.
  - Verify the `google` provider version in `versions.tf` supports these (may need a bump).
- `infra/envs/prod/cloud_run.tf` (`module "run_worker_ocr"`) — gate on a new `var.ocr_vlm_enabled`:
  when true → `gpu = 1`, `cpu = "4"`, `memory = "16Gi"`, mount the models bucket, add env
  `PRT_OCR_ENGINE = "receipt-vlm-500m"` + the model path; when false → unchanged Groq config.
  Confirm **L4 availability in `europe-west1`** and request the *"Total Nvidia L4 GPU allocation"*
  quota first.

### 5. Build, push, deploy
- `gcloud builds submit . --config=workers/ocr/cloudbuild.yaml --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD)`
- Bump `worker_ocr_image_tag` in `infra/envs/prod/variables.tf`, set `ocr_vlm_enabled=true`,
  `terraform apply -target=module.run_worker_ocr`.

## Verification (end-to-end)

1. **Local first (cheapest signal):** in the worker dir on the `.venv`, set the four `RECEIPT_VLM_*`
   env vars at the merged checkpoint and run `run_ocr(image_bytes, "receipt-vlm-500m")` on a sample —
   confirm valid JSON. (`dev_ocr/vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb` already
   exercises the same provider path.)
2. **Container parity:** `docker build -f workers/ocr/Dockerfile .`; run with the model mounted and
   `HF_HUB_OFFLINE=1`; confirm it loads with no network and `/healthz` is green.
3. **Deployed:** flip `ocr_vlm_enabled=true`, drop a test image into
   `gs://price-tracker-prod-01-bronze/tickets/raw/...` (triggers the `ticket-uploaded` push), then
   check Cloud Logging, the `tickets`/`prix_extraits` rows in Cloud SQL, and per-request latency.
   Flip back to Groq when done.

## Risks / caveats to weigh

- **GPU cost on a mostly-Groq worker.** The whole revision carries the L4 while enabled. The
  `ocr_vlm_enabled` toggle + `min_instances=0` (scale-to-zero) limits cost to "while demoing," but
  there's no per-request GPU. If cost matters, the separate-service option is cleaner.
- **Cold start.** Loading a 1.8 GB checkpoint + CUDA init is tens of seconds; within the 540s timeout
  but the first Pub/Sub push may retry. Consider `min_instances=1` during a demo window.
- **L4 region/quota.** Must confirm L4 in `europe-west1` and have approved L4 quota, or the apply
  fails.
- **Redundant weights (optional optimization).** The merged `.pt` already contains the full CLIP+LM
  weights, yet `ReceiptVLM.__init__` still `from_pretrained`s them (then overwrites). Baking the HF
  cache makes this work offline; a later optimization is to construct the backbones from config only
  (`local_files_only`/no-pretrained) to shrink the image and speed load — a small change in
  `receipt_vlm/models/vlm.py`, not required for correctness.

## Critical files
- `workers/ocr/pricetracker_ocr/ocr.py` — engine wiring (add VLM branch)
- `workers/ocr/pricetracker_ocr/config.py` — reuse `prt_ocr_model_uri`
- `workers/ocr/pyproject.toml` + `workers/ocr/Dockerfile` — deps + HF cache bake + offline env (and conflict resolution)
- `infra/modules/cloud_run/main.tf` + `variables.tf` — GPU + GCS volume support
- `infra/envs/prod/cloud_run.tf` + `variables.tf` — `ocr_vlm_enabled` toggle, sizing, env, image tag
- Reference (unchanged): `dev_ocr/src/receipt_ocr/backends/vlm/receipt_vlm_provider.py`,
  `dev_ocr/vlm_training/receipt_vlm/models/vlm.py`, `infra/envs/prod/storage.tf` (models bucket)
