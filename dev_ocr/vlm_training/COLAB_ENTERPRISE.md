# Vertex AI Colab Enterprise training — receipt VLM

Train the 3-phase curriculum on a **Vertex AI Colab Enterprise runtime** (a managed,
GPU-backed notebook runtime). Code + data come from a **Cloud Storage (GCS) bucket**, and the
bucket is **mounted with `gcsfuse`** so every checkpoint is written *directly into the bucket*
the instant the trainer saves it — a teardown at any moment loses nothing already saved.

Notebook: [`notebooks/train_receipt_vlm_colab_enterprise.ipynb`](notebooks/train_receipt_vlm_colab_enterprise.ipynb).

## Workbench vs Colab Enterprise (why this notebook is different)

Both are "Vertex AI notebooks" but they are different products:

| | Workbench | **Colab Enterprise** |
|---|---|---|
| What it is | a JupyterLab **VM** you own and manage | a managed **runtime** spun up from a *runtime template* |
| Working disk | **persistent** — `/home/jupyter` survives Stop/Start | **ephemeral** — `/content`, wiped when the runtime is torn down |
| Lifecycle | you explicitly Stop / Start the VM | **auto idle shutdown** (default ~180 min) + a max-runtime cap |
| GPU selection | chosen per instance at create time | fixed in the **runtime template** (can't change from the notebook) |
| Billing | per hour while the VM is *running* | per hour while the *runtime* is up |
| Auth | runs as a service account; `gsutil` pre-authenticated | same — runs as the template's service account |
| Best for | long unattended runs, heavy local I/O, you want a stable box | quick GPU notebooks, sharing, teams already on Colab |

**Practical consequences for training:**

- Paths move from `/home/jupyter/...` (Workbench) to `/content/...` (Colab Enterprise).
- Because `/content` is ephemeral *and* the runtime can idle-shut-down mid-run, the bucket is
  **mounted with `gcsfuse`** and `checkpoint_dir` points at the mount. The trainer saves
  `phase*_best.pt` on **every validation improvement** (these are small adapter-only LoRA files),
  and each save lands in GCS immediately — so a teardown at any moment loses nothing already saved,
  not even mid-phase progress. (The Workbench notebook instead syncs once per *phase*.)
- You can't pick the GPU from the notebook — it's baked into the runtime template.
- A long-running training cell counts as activity, so the idle timer mostly bites during
  the *silent* startup downloads. Set the template's idle shutdown high enough (60–180 min).

## Before you open the notebook

1. **GCP project** with billing enabled and the **Vertex AI** + **Cloud Storage** APIs on.
2. **A GCS bucket** (same region as the runtime keeps egress free), e.g.
   ```powershell
   gsutil mb -l europe-west1 gs://YOUR_BUCKET
   ```
3. **Pack the bundle on your PC and upload it** (reuses the existing self-contained zip):
   ```powershell
   cd dev_ocr\vlm_training
   .venv\Scripts\python scripts\zip_selfcontained_colab.py
   gsutil cp colab_upload\receipt_vlm_colab_bundle.zip gs://YOUR_BUCKET/receipt_vlm/
   ```
   Phase 1 doesn't need real photos — `--no-images` makes a smaller bundle if you only run phase 1.

## Create the runtime template

Vertex AI → **Colab Enterprise** → **Runtime templates** → **Create**:

| Setting | Value |
|---------|-------|
| Region | same as the bucket (e.g. `europe-west1`) |
| Machine type | `n1-standard-8` (T4) or `g2-standard-12` (L4) |
| GPU | **NVIDIA T4** (cheapest) / L4 / A100 |
| Disk | 100 GB+ (HF cache + CORD + checkpoints) |
| Idle shutdown | 60–180 min (high enough to survive the startup downloads) |
| Service account | Compute default SA, or a custom one |

**Permissions:** the runtime runs as that service account. Grant it **Storage Object Admin**
on the bucket so it can read the bundle and write checkpoints:

```powershell
gsutil iam ch serviceAccount:SA_EMAIL:roles/storage.objectAdmin gs://YOUR_BUCKET
```

`gcloud`/`gsutil` are pre-installed on the runtime and authenticate as that service account
automatically — no key files needed. (Cell 1 prints the active identity and lists the bucket
so you catch a missing role before training starts.)

## Run the notebook

1. Vertex AI → **Colab Enterprise** → **Notebooks** → **Import**, upload
   `dev_ocr/vlm_training/notebooks/train_receipt_vlm_colab_enterprise.ipynb`.
2. **Connect** it to a runtime created from your template.
3. Edit **cell 0**: set `GCS_BUCKET` (and `GCS_PREFIX` if not `receipt_vlm`).
4. **Run all cells** top to bottom.

Layout the notebook uses:

```
Runtime working disk (EPHEMERAL — lost on teardown / idle shutdown):
  /content/receipt_vlm/repo/          ← extracted bundle (code; disposable)

gcsfuse mount of the bucket at /content/gcs (writes go STRAIGHT to GCS):
  /content/gcs/receipt_vlm/checkpoints/  ==  gs://YOUR_BUCKET/receipt_vlm/checkpoints/

GCS bucket (durable; survives teardown):
  gs://YOUR_BUCKET/receipt_vlm/receipt_vlm_colab_bundle.zip
  gs://YOUR_BUCKET/receipt_vlm/checkpoints/phase{1,2,3}_best.pt   ← written on every val improvement
  gs://YOUR_BUCKET/receipt_vlm/checkpoints/receipt_vlm_500m_merged.pt   ← final export
```

`checkpoint_dir` is the mount, so the trainer's normal `torch.save` writes land in the bucket —
no separate "upload" step, and no progress is held only on the ephemeral disk.

## Resume after an idle shutdown / on a fresh runtime

Because the checkpoints live in the bucket (mounted at `/content/gcs`), there's **no restore
step** — finished phases are already visible on a fresh runtime. To continue:

1. Reconnect a runtime, run cells 0–5 (cell 2 re-mounts the bucket; cell 5b lists what's already there).
2. In cell 0, set `RUN_PHASE_1 = False` (and `RUN_PHASE_2 = False`) for finished phases.
3. Run cell 6 — it `--resume`s straight from the checkpoint in the bucket.

## After training

1. Download the merged model to your PC:
   ```powershell
   gsutil cp gs://YOUR_BUCKET/receipt_vlm/checkpoints/receipt_vlm_500m_merged.pt .
   ```
2. **Delete the runtime** (Colab Enterprise → *Runtimes* → select → *Delete*) to stop billing.
3. Local inference:
   ```powershell
   $env:RECEIPT_OCR_BACKEND   = "vlm"
   $env:RECEIPT_VLM_MODEL     = "receipt-vlm-500m"
   $env:RECEIPT_VLM_MODE      = "json"
   $env:RECEIPT_VLM_MODEL_PATH = "D:\path\to\receipt_vlm_500m_merged.pt"
   ```

## Config files

The notebook reuses the Colab phase configs (`phase{1,2,3}_colab.yaml`), which merge
`colab_paths.yaml` (batch 8, on-the-fly synthetic). Cell 5 rewrites `colab_paths.yaml`
at runtime to point `checkpoint_dir` at the gcsfuse mount (`/content/gcs/...`, i.e. the bucket)
and the real-data dirs at the local-disk bundle.

## Time / cost estimates

| Phase | T4 | A100 |
|-------|----|------|
| 1 | 45–90 min | ~20–30 min |
| 2 | 1–2 h | ~30–45 min |
| 3 | 30–60 min | ~15–20 min |
| **Total** | **~3–4 h** | **~1–1.5 h** |

A T4 on `n1-standard-8` is the cheapest sensible choice (~US$0.7–1.0/h all-in). **Delete the
runtime** when done — a forgotten running GPU runtime is the main way to overspend here.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `AccessDeniedException` / cell 1 bucket check fails / `gcsfuse mount failed` | Grant the runtime SA `roles/storage.objectAdmin` on the bucket |
| `gcsfuse: command not found` | Cell 2 apt-installs it; if that fails, the runtime image is unusual — install gcsfuse manually or use the Workbench notebook |
| `train.py not found after materialize` | Wrong `GCS_BUCKET`/`GCS_PREFIX`, or bundle not uploaded |
| `No training samples` for phase 2 | Bundle built with `--no-images`; rebuild without it |
| CUDA OOM | Set `FORCE_SMALL_BATCH = True` in cell 0 (batch 8 → 4) |
| Runtime shut down mid-run | Reconnect a runtime, run cells 0–5 (no restore needed — checkpoints are in the bucket), skip finished phases (see *Resume*) |
| Idle shutdown during startup downloads | Raise the template's idle-shutdown timeout |
| CORD download slow | First phase-1 epoch only — but it re-downloads on a fresh runtime (ephemeral disk) |

See also [`VERTEX.md`](VERTEX.md) (the same curriculum on Workbench), `COLAB.md`, and
`dev_ocr/documentation.md` entries 11–12.
