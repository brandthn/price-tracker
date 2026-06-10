"""Merge LoRA into base weights and export a single inference-ready .pt.

The output is consumed by ``receipt_ocr.backends.vlm.receipt_vlm_provider``
via ``RECEIPT_VLM_MODEL_PATH``.

Usage:
    python scripts/export_checkpoint.py \
        --checkpoint checkpoints/phase3_best.pt \
        --output checkpoints/receipt_vlm_500m_merged.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="training checkpoint (.pt)")
    parser.add_argument("--output", required=True, help="merged output path (.pt)")
    args = parser.parse_args()

    import torch

    from receipt_vlm.models.vlm import ReceiptVLM

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model_cfg = (checkpoint.get("config") or {}).get("model", {})

    model = ReceiptVLM(
        lora_rank=model_cfg.get("lora_rank", 16),
        lora_alpha=model_cfg.get("lora_alpha", 32.0),
        lora_dropout=model_cfg.get("lora_dropout", 0.05),
    )
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    merged = model.export_merged_state()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(merged, output)

    size_mb = output.stat().st_size / 1e6
    print(f"Merged checkpoint written: {output} ({size_mb:.0f} MB)")


if __name__ == "__main__":
    main()
