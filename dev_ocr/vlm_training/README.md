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

# 2. Pseudo-label real photos with the Groq provider (then review manually)
python scripts/pseudo_label.py --images ../data/raw/images_tickets_caisse --output data/real_labels

# 3. Train the 3-phase curriculum
python scripts/train.py --config configs/phase1.yaml
python scripts/train.py --config configs/phase2.yaml --resume checkpoints/phase1_best.pt
python scripts/train.py --config configs/phase3.yaml --resume checkpoints/phase2_best.pt

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
