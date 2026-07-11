# Google Colab training — receipt VLM

Train the 3-phase curriculum on a Colab GPU (T4 / A100). Checkpoints are saved to
**Google Drive** so they survive session disconnects.

## Before you open Colab

1. **Google account** with Drive space (~5 GB free for checkpoints + HF cache).
2. **GPU runtime:** Colab → *Runtime* → *Change runtime type* → **T4 GPU** (or A100 Pro).
3. **Push this repo** to GitHub (or be ready to upload `dev_ocr/` as a zip).

### Pack real photos + labels (phases 2–3)

From your PC:

```powershell
cd dev_ocr\vlm_training
.venv\Scripts\python scripts\zip_colab_upload.py
```

Upload `colab_upload/receipt_vlm_colab_data.zip` to Google Drive (any folder). The notebook will unzip it into `My Drive/receipt_vlm/`.

**If local disk is full:** skip the zip and upload these folders directly to `My Drive/receipt_vlm/`:
- `dev_ocr/data/raw/images_tickets_caisse/`
- `dev_ocr/vlm_training/data/real_labels/`

Phase 1 does **not** need real photos (CORD + on-the-fly synthetic only).

### Optional: continue from a local checkpoint

If you have `checkpoints/phase1_best.pt` from a local run, upload it to:

`My Drive/receipt_vlm/checkpoints/phase1_best.pt`

Then skip phase 1 in the notebook and run phase 2 with `--resume`.

---

## Open the notebook

1. In Colab: **File → Upload notebook**  
   Upload `dev_ocr/vlm_training/notebooks/train_receipt_vlm_colab.ipynb`

   **Or** after cloning the repo in Colab, open the notebook from the file tree.

2. Run cells **top to bottom**. Edit the **Configuration** cell if your repo URL or Drive folder differs.

3. Default Drive layout (created by the notebook):

```
My Drive/receipt_vlm/
├── checkpoints/          ← phase1_best.pt, phase2_best.pt, …
├── images_tickets_caisse/
├── real_labels/
└── receipt_vlm_500m_merged.pt   ← final export
```

---

## After training

1. Download `receipt_vlm_500m_merged.pt` from Drive to your PC.
2. Local inference:

```powershell
$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODEL = "receipt-vlm-500m"
$env:RECEIPT_VLM_MODE = "json"
$env:RECEIPT_VLM_MODEL_PATH = "D:\path\to\receipt_vlm_500m_merged.pt"
```

3. Optional: run `scripts/evaluate.py` on Colab (needs reviewed test labels + `GROQ_API_KEY` for baseline).

---

## Config files

| File | Role |
|------|------|
| `configs/colab_paths.yaml` | Drive paths, batch_size 8, on-the-fly synthetic |
| `configs/phase1_colab.yaml` | Projector warmup, 5 epochs |
| `configs/phase2_colab.yaml` | + LoRA + real photos, 10 epochs |
| `configs/phase3_colab.yaml` | Low LR alignment, 5 epochs |

CLI equivalent:

```bash
python scripts/train.py --config configs/phase1_colab.yaml
python scripts/train.py --config configs/phase2_colab.yaml --resume /content/drive/MyDrive/receipt_vlm/checkpoints/phase1_best.pt
```

---

## Time estimates (T4, on-the-fly synthetic)

| Phase | ~Duration |
|-------|-----------|
| 1 | 45–90 min |
| 2 | 1–2 h |
| 3 | 30–60 min |
| **Total** | ~3–4 h |

A100 Pro is roughly 3× faster.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `No training samples` for phase 2 | Unzip real data; check `real_labels/splits.json` exists |
| CUDA OOM | Notebook sets `batch_size: 4` override; keep `gradient_checkpointing: true` |
| Session disconnected | Re-run from last completed phase using `--resume` on Drive checkpoint |
| `tokenizers` version error | Notebook pins `tokenizers>=0.22,<=0.23` |
| CORD download slow | First phase 1 epoch only; cached afterward in Colab |

See also Entry 11–12 in `dev_ocr/documentation.md`.
