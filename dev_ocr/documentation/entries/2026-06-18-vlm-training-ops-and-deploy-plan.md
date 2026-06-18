## Version 0.2.0 (unreleased)

### Entry 14 — 2026-06-18 (UTC+2)

**Scope:** Training-ops hardening for the receipt VLM (durable cloud checkpoints, per-epoch snapshots + mid-phase auto-resume), a standalone merge-and-evaluate notebook that runs a checkpoint through the real `receipt_ocr` pipeline against the labelled test set, a new **Vertex AI Colab Enterprise** training path, and a **GCP deployment plan** for serving the VLM from the OCR worker. No runtime/library behaviour changed — this is training + tooling + docs.

#### Motivation

Training on free/cloud GPUs (Colab, Kaggle, Vertex) kept losing progress: ephemeral disks are wiped on idle-shutdown, and only `phaseN_best.pt` was synced, only at phase boundaries — a mid-phase stop lost every epoch since the last boundary. We also needed a fast way to package a *mid-training* checkpoint (e.g. phase 2) and exercise it through the actual OCR pipeline before training finishes, and a written plan for how the trained model would reach the deployed GCP worker.

#### What was implemented

| Area | Path | Change |
|------|------|--------|
| Per-epoch checkpoints | `vlm_training/receipt_vlm/training/trainer.py` | `train_phase` saves `phase{p}_epoch{NN}_loss{L}.pt` every epoch (keeps `phaseN_best.pt` for export); new `start_epoch` arg resumes mid-phase and fast-forwards the cosine LR schedule |
| Auto-resume | `vlm_training/scripts/train.py` | `resolve_resume()`: latest same-phase epoch snapshot (mid-phase recovery) → explicit `--resume` → last checkpoint of the previous phase; passes `start_epoch` to the trainer |
| Colab Enterprise | `vlm_training/notebooks/train_receipt_vlm_colab_enterprise.ipynb`, `vlm_training/COLAB_ENTERPRISE.md` | New training path; mounts the GCS bucket with `gcsfuse` so every checkpoint writes straight to the bucket (zero-loss on teardown). Includes a Workbench-vs-Colab-Enterprise comparison |
| Kaggle durability | `vlm_training/notebooks/train_receipt_vlm_kaggle.ipynb` | Pushes checkpoints to a durable Kaggle **Dataset** (per-epoch with `SAVE_EVERY_EPOCH`, else per-phase); restores all `phase*.pt` on resume; auth via Kaggle Secrets |
| Merge + evaluate | `vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb` | New local notebook: merge any `phase{1,2,3}` checkpoint → run the **real `receipt_ocr` pipeline** (`extract_receipt`, VLM provider) on the labelled real receipts (`load_real_samples`), printing prediction-vs-gold + the `evaluate.py` acceptance metrics |
| Deployment plan | `documentation/receipt_vlm_gcp_deployment_plan.md` | Plan to serve `receipt-vlm-500m` from `prt-prod-worker-ocr` (in-worker, L4 GPU, opt-in toggle); readiness gaps + steps + risks |
| README pointers | `vlm_training/README.md` | Links the Workbench vs Colab Enterprise paths |

#### Checkpoint naming + resume model

- Filenames embed phase, epoch (1-indexed = epochs completed), and val-loss: `phase2_epoch07_loss0.1543.pt`.
- Resume precedence in `resolve_resume()` (checked across 6 scenarios): same-phase epoch snapshot → `--resume` → previous phase's last snapshot (legacy `phaseN_best.pt` fallback). Backward-compatible: the other notebooks' `--resume phaseN_best.pt` still works.
- Checkpoints stay **adapter-only (~45 MB)**; optimizer state is not stored, so a mid-phase resume reloads weights and continues with a fresh optimizer (LR schedule fast-forwarded). All notebooks now emit per-epoch snapshots.

#### Merge-and-evaluate notebook notes

- Runs the deployed code path (`extract_receipt`), not a bypass, so the numbers reflect production behaviour.
- Defaults `REQUIRE_REVIEWED=False` because the project labels are still pseudo-labels (none marked reviewed) — otherwise the `test` split loads 0 samples.
- Must run on the project `.venv` kernel (system Python has an incompatible `tokenizers`); cell 1 warns, cell 2 runs the merge on the venv interpreter and surfaces the real error instead of an opaque `CalledProcessError`.

#### GCP deployment — readiness (summary)

The VLM is integrated in the `receipt_ocr` library, but the deployed worker is **Groq-only**. Gaps: engine wiring in `workers/ocr/pricetracker_ocr/ocr.py`, inference deps (CUDA torch + transformers + `receipt_vlm`) in the worker image, model distribution (1.8 GB `.pt` → `*-models` GCS bucket + Cloud Run volume), baked HF cache for offline cold start, L4 GPU sizing, `modules/cloud_run` GPU+volume support, and pre-existing merge-conflict markers in the worker `Dockerfile`/`config.py`/`pyproject.toml`. Full plan in `receipt_vlm_gcp_deployment_plan.md`.

#### Not done / still pending

- Eval results vs Groq on the reviewed test split (blocked on hand-reviewing the 5 test labels; training still in progress) — to be **Entry 15**.
- Multi-GPU (DDP) on Kaggle T4×2 considered but deferred (modest ~1.4–1.6× gain vs. the rework + NCCL / gradient-checkpointing risk).
- No deployment executed; the plan is for team review.

#### References

- Deployment plan: [`documentation/receipt_vlm_gcp_deployment_plan.md`](../receipt_vlm_gcp_deployment_plan.md)
- Colab Enterprise guide: [`vlm_training/COLAB_ENTERPRISE.md`](../../vlm_training/COLAB_ENTERPRISE.md)
- Merge/eval notebook: [`vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb`](../../vlm_training/notebooks/merge_and_infer_receipt_vlm.ipynb)
- Training architecture & local pipeline: Entries 11–13 in `documentation.md`

---
