# Vertex AI training — receipt VLM

Train the 3-phase curriculum on a **Vertex AI Workbench** instance (managed JupyterLab
with a GPU). Code + data come from a **Cloud Storage (GCS) bucket**, and checkpoints are
synced back to that bucket after every phase, so a stop/delete never loses progress.

Unlike Kaggle/Colab there is **no session time limit** — but the instance **bills per hour
while running**. Stop it from the console as soon as training finishes.

## Before you open the notebook

1. **GCP project** with billing enabled and the **Vertex AI** + **Cloud Storage** APIs on.
2. **A GCS bucket** (same region as your instance keeps egress free), e.g.
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

## Create the Workbench instance

Vertex AI → **Workbench** → **Instances** → **Create New**:

| Setting | Value |
|---------|-------|
| Region | same as the bucket (e.g. `europe-west1`) |
| Machine type | `n1-standard-8` (T4/V100) or `g2-standard-12` (L4) |
| GPU | **NVIDIA T4** (cheapest) / L4 / A100; tick *Install GPU driver automatically* |
| Environment | a PyTorch / CUDA image |
| Disk | 100 GB+ (HF cache + CORD + checkpoints) |

**Permissions:** the instance runs as a service account (Compute default, or a custom one).
Grant it **Storage Object Admin** on the bucket so it can read the bundle and write checkpoints:

```powershell
gsutil iam ch serviceAccount:SA_EMAIL:roles/storage.objectAdmin gs://YOUR_BUCKET
```

`gsutil` is pre-installed on Workbench and authenticates as that service account automatically —
no key files needed.

## Run the notebook

1. Open JupyterLab on the instance, upload (or `git clone`) and open
   `dev_ocr/vlm_training/notebooks/train_receipt_vlm_vertex.ipynb`.
2. Edit **cell 0**: set `GCS_BUCKET` (and `GCS_PREFIX` if not `receipt_vlm`).
3. **Run all cells** top to bottom.

Layout the notebook uses:

```
Local (persistent home disk, survives stop/start):
  /home/jupyter/receipt_vlm/repo/          ← extracted bundle
  /home/jupyter/receipt_vlm/checkpoints/   ← phase*_best.pt, merged model

GCS bucket (durable; survives instance delete; used for resume):
  gs://YOUR_BUCKET/receipt_vlm/receipt_vlm_colab_bundle.zip
  gs://YOUR_BUCKET/receipt_vlm/checkpoints/phase{1,2,3}_best.pt
  gs://YOUR_BUCKET/receipt_vlm/receipt_vlm_500m_merged.pt   ← final export
```

## Resume after a stop / on a fresh instance

Checkpoints are pushed to GCS after each phase. To continue:

1. Run cells 0–4, then **cell 4b** (pulls `phase*_best.pt` from the bucket).
2. In cell 0, set `RUN_PHASE_1 = False` (and `RUN_PHASE_2 = False`) for finished phases.
3. Run cell 5 — it `--resume`s from the restored checkpoint.

## After training

1. Download the merged model to your PC:
   ```powershell
   gsutil cp gs://YOUR_BUCKET/receipt_vlm/receipt_vlm_500m_merged.pt .
   ```
2. **Stop the instance** (Workbench → select instance → *Stop*) to stop billing.
3. Local inference:
   ```powershell
   $env:RECEIPT_OCR_BACKEND   = "vlm"
   $env:RECEIPT_VLM_MODEL     = "receipt-vlm-500m"
   $env:RECEIPT_VLM_MODE      = "json"
   $env:RECEIPT_VLM_MODEL_PATH = "D:\path\to\receipt_vlm_500m_merged.pt"
   ```

## Config files

The notebook reuses the Colab phase configs (`phase{1,2,3}_colab.yaml`), which merge
`colab_paths.yaml` (batch 8, on-the-fly synthetic). Cell 4 rewrites `colab_paths.yaml`
at runtime to point `checkpoint_dir` and the real-data dirs at the local disk.

## Time / cost estimates

| Phase | T4 | A100 |
|-------|----|------|
| 1 | 45–90 min | ~20–30 min |
| 2 | 1–2 h | ~30–45 min |
| 3 | 30–60 min | ~15–20 min |
| **Total** | **~3–4 h** | **~1–1.5 h** |

A T4 on `n1-standard-8` is the cheapest sensible choice (~US$0.7–1.0/h all-in). **Stop the
instance** when done — a forgotten running GPU instance is the main way to overspend here.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `AccessDeniedException` on gsutil | Grant the instance SA `roles/storage.objectAdmin` on the bucket |
| `train.py not found after materialize` | Wrong `GCS_BUCKET`/`GCS_PREFIX`, or bundle not uploaded |
| `No training samples` for phase 2 | Bundle built with `--no-images`; rebuild without it |
| CUDA OOM | Set `FORCE_SMALL_BATCH = True` in cell 0 (batch 8 → 4) |
| Instance stopped mid-run | Restart it, run cell 4b, skip finished phases (see *Resume*) |
| CORD download slow | First phase-1 epoch only; cached on the persistent disk afterward |

See also `COLAB.md` (the same curriculum on Colab) and `dev_ocr/documentation.md` entries 11–12.
