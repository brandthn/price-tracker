### Entry 19 — 2026-07-10 (UTC+2)

**Scope:** Handoff list of the **model artifacts** the devops team must upload to GCS before the OCR
backend workers (Entry 18) can serve traffic. Documentation only — no code changed.

#### Which workers need weights at all

Three of the six. The other three need **nothing uploaded**, and time is wasted looking for files
that do not exist:

| Worker | Weights come from | Uploaded to GCS? |
|---|---|---|
| `worker-ocr-paddle` | Paddle CDN, **baked into the image** at build | ❌ |
| `worker-ocr-ppocrv4` | Paddle CDN, **baked into the image** at build | ❌ |
| `worker-ocr-vlm-groq` | Remote API — no local model | ❌ |
| `worker-ocr-vlm-moondream` | GCS at cold start | ✅ 1 file |
| `worker-ocr-vlm-receipt` | GCS at cold start (+ HF backbones baked in) | ✅ 1 file |
| `worker-ocr-vlm-scratch` | GCS at cold start | ✅ 2 files |

`worker-ocr-vlm-receipt` is the subtle one: its **merged checkpoint** travels through GCS, but its
CLIP ViT-B/16 and SmolLM2-360M backbones are baked into the image with `HF_HUB_OFFLINE=1`. Cloud Run
runs `vpc_egress = PRIVATE_RANGES_ONLY`, so `from_pretrained` cannot reach the HuggingFace Hub at cold
start. Do not try to upload the backbones.

#### The four artifacts

Bucket `gs://price-tracker-prod-01-models` (exists, versioning on). The object paths are **not
free-form** — they are the defaults of `infra/envs/prod/variables_ocr_backends.tf`; uploading
elsewhere means overriding those variables too.

| # | Local file | → GCS object path | Size | Worker |
|---|---|---|---|---|
| 1 | `data/models/moondream-0_5b-int8.mf` ⚠️ **must be generated first** | `vlm/moondream/v1/moondream-0_5b-int8.mf` | 693 MB | `ocr-vlm-moondream` |
| 2 | `vlm_training/checkpoints/receipt_vlm_500m_merged.pt` | `vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt` | 1.82 GB | `ocr-vlm-receipt` |
| 3 | `vlm_training/checkpoints/ocr_vlm_epoch050_loss0.3619.pt` | `vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt` | 105 MB | `ocr-vlm-scratch` |
| 4 | `vlm_training/checkpoints/tokenizer_20260607_0900.json` | `vlm/ocr-vlm-scratch/v1/tokenizer_20260607_0900.json` | 993 B | `ocr-vlm-scratch` |

Paths 1 and 3–4 are relative to `dev_ocr/`; the `gsutil` commands below run from the **monorepo root**.

**(3) and (4) are a pair.** The from-scratch model is the only backend needing two artifacts: its
checkpoint is useless without the character tokenizer that was fitted with it. Ship them together.

#### ⚠️ The Moondream file does not exist in the repo

`data/models/` is gitignored and empty on a fresh clone — there is no `.mf` anywhere. It must be
produced before any upload:

```bash
cd dev_ocr
python scripts/download_moondream_weights.py     # 593 MB .mf.gz from HF → 693 MB .mf in data/models/
```

The script deletes the `.mf.gz` after decompressing, and `data/models/` is gitignored. Upload the
**decompressed `.mf`**, not the archive: `MoondreamProvider` passes the path straight to
`md.vl(model=...)`. The pinned source is `vikhyatk/moondream2` at revision `9dddae84…` (see the
script) — the same weights the local benchmarks in Entries 11–13 were run against.

#### Commands (from the monorepo root)

```bash
gsutil cp dev_ocr/data/models/moondream-0_5b-int8.mf \
  gs://price-tracker-prod-01-models/vlm/moondream/v1/

gsutil cp dev_ocr/vlm_training/checkpoints/receipt_vlm_500m_merged.pt \
  gs://price-tracker-prod-01-models/vlm/receipt-vlm/v1/

gsutil cp dev_ocr/vlm_training/checkpoints/ocr_vlm_epoch050_loss0.3619.pt \
          dev_ocr/vlm_training/checkpoints/tokenizer_20260607_0900.json \
          gs://price-tracker-prod-01-models/vlm/ocr-vlm-scratch/v1/
```

#### No IAM change is required

`module.bucket_models` in `infra/envs/prod/storage.tf` already grants `object_viewer` to the worker
service account, which is the identity all six workers run as. `worker/weights.py` reads the bucket
with ADC. Nothing to grant, nothing to rotate.

#### Versioning is by prefix, never by overwrite

The `v1/` segment is deliberate. To ship a new checkpoint, upload it under `v2/` and bump the matching
`*_model_gcs_uri` variable. **Do not overwrite an object in place**: `ensure_weights` skips the
download when the local file already matches the blob size, so a warm instance would keep serving the
old weights while a cold one picks up the new ones — the two would silently disagree about what the
model is.

#### Why epoch050 for the from-scratch model

`ocr_vlm_epoch050_loss0.3619.pt` beats `ocr_vlm_epoch040_loss0.2265.pt` on **real** data — WildReceipt
ANLS 0.183 vs 0.170, `product_recall` roughly doubled (`vlm_training/checkpoints/eval_epoch0*.json`),
and it is the "current best checkpoint" recorded in
[`ocr_vlm_from_scratch_roadmap.md`](../ocr_vlm_from_scratch_roadmap.md). Its **higher loss number is
not a regression** — 0.3619 is the loss on the Stage B synthetic+real mix, while 0.2265 is on
synthetic only. Choosing by loss alone would pick the wrong checkpoint here.

Switching back is a one-line change to `ocr_vlm_scratch_model_gcs_uri` plus uploading the other file.

#### References

- Workers and their contract: Entry 18 in this file
- Weight bootstrap: `libs/pricetracker_receipt_pipeline/pricetracker_receipt_pipeline/worker/weights.py`
- GCS paths and sizing: `infra/envs/prod/variables_ocr_backends.tf`, `cloud_run_ocr_backends.tf`
- Per-worker build/deploy commands: each `workers/ocr-*/README.md` and `cloudbuild.yaml` header

---
