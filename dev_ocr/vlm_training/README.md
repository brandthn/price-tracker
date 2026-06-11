# receipt_vlm — hybrid French receipt VLM (training side)

Training code for the ~466M-parameter Vision-Language Model described in
`dev_ocr/documentation/receipt_vlm_spec_adapted.md`:

- **CLIP ViT-B/16** vision encoder — frozen pretrained (~86M)
- **MultimodalProjector** — from scratch (cross-attention + 32 learned query tokens, ~14M)
- **SmolLM2-360M-Instruct** decoder — frozen pretrained (~360M), adapted via
- **hand-rolled LoRA** adapters on every `q_proj`/`v_proj` (~4M, no `peft`)
- **JSON-constrained decoding** — from-scratch token-mask state machine (0 params)

The model is trained to emit the project's **canonical schema** directly
(`{"ticket": {"date", "chaine_supermarche", "adresse", "produits": [...]}}`), so the
existing `receipt_ocr` parsing/validation pipeline works unchanged at inference.

## Install

```bash
cd dev_ocr/vlm_training
pip install -r requirements-training.txt
pip install -e .                # this package
pip install -e ..               # receipt_ocr (constants / image prep / Groq pseudo-labels)
```

## Workflow

```bash
# 1. Generate synthetic French receipts (canonical labels)
python scripts/generate_synthetic.py --n 5000 --output data/synthetic

# Optional: visually varied preview set (multi-layout + capture noise)
python scripts/generate_synthetic.py --n 100 --output data/synthetic_preview_varied \\
    --diverse --distort --distort-intensity heavy

# 2. Pseudo-label real photos with the Groq provider (then review manually)
python scripts/pseudo_label.py --images ../data/raw/images_tickets_caisse --output data/real_labels

# 3. Train the 3-phase curriculum
python scripts/train.py --config configs/phase1.yaml
python scripts/train.py --config configs/phase2.yaml --resume checkpoints/phase1_best.pt
python scripts/train.py --config configs/phase3.yaml --resume checkpoints/phase2_best.pt

# Local RTX 2070 (~2–8 h): on-the-fly diverse synthetic, no full CORD download load
python scripts/train.py --config configs/phase1_local.yaml
python scripts/train.py --config configs/phase2_local.yaml --resume checkpoints/phase1_best.pt
python scripts/train.py --config configs/phase3_local.yaml --resume checkpoints/phase2_best.pt

# Google Colab (~3–4 h on T4): checkpoints saved to Drive — see COLAB.md
python scripts/zip_colab_upload.py   # pack real photos + labels for Drive upload
# then open notebooks/train_receipt_vlm_colab.ipynb in Colab

# 4. Merge LoRA + export a single inference-ready .pt
python scripts/export_checkpoint.py --checkpoint checkpoints/phase3_best.pt \
    --output checkpoints/receipt_vlm_500m_merged.pt

# 5. Evaluate side-by-side vs the Groq baseline on the held-out set
python scripts/evaluate.py --checkpoint checkpoints/receipt_vlm_500m_merged.pt \
    --images ../data/raw/images_tickets_caisse --labels data/real_labels --split test
```

## Inference (runtime side)

The merged checkpoint is consumed by `receipt_ocr.backends.vlm.receipt_vlm_provider`:

```bash
RECEIPT_OCR_BACKEND=vlm
RECEIPT_VLM_MODEL=receipt-vlm-500m
RECEIPT_VLM_MODE=json
RECEIPT_VLM_MODEL_PATH=/models/receipt_vlm_500m_merged.pt
```

This package may import `receipt_ocr`; the reverse is forbidden (except the single
provider file, which lazily imports `receipt_vlm` model code at inference time).

## Google Colab

Full guide: [`COLAB.md`](COLAB.md)

1. Push this repo (branch `ocr_worker_module` or your training branch).
2. Pack real data: `python scripts/zip_colab_upload.py` → upload `colab_upload/receipt_vlm_colab_data.zip` to Drive.
   If disk is tight, upload `../data/raw/images_tickets_caisse/` and `data/real_labels/` folders directly to `My Drive/receipt_vlm/` instead.
3. Colab → T4 GPU → open `notebooks/train_receipt_vlm_colab.ipynb`, set `REPO_URL` and `DATA_ZIP_ON_DRIVE`, run all cells.
4. Download `My Drive/receipt_vlm/receipt_vlm_500m_merged.pt`.

Phase configs (`phase*_colab.yaml`) auto-merge `colab_paths.yaml` (Drive paths, batch 8, on-the-fly synthetic).
