"""Refond les LoRA dans les poids de base et sort un seul .pt pret pour l'inference.

Le checkpoint d'entrainement ne contient que le projecteur et les LoRA. Ici on rejoue
l'init pre-entrainee, on fusionne, et on ecrit un modele ordinaire, sans adaptateur.

    python scripts/export_checkpoint.py --checkpoint checkpoints/phase3_best.pt \
        --output checkpoints/receipt_vlm_500m_merged.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="checkpoint d'entrainement (.pt)")
    parser.add_argument("--output", required=True, help="ou ecrire le .pt fusionne")
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
    # Le checkpoint ne contient que le projecteur et les LoRA. Les backbones geles
    # viennent de l'init pre-entrainee ci-dessus, donc chargement non-strict.
    result = model.load_state_dict(checkpoint["model_state"], strict=False)
    if result.unexpected_keys:
        raise RuntimeError(f"unexpected keys in checkpoint: {result.unexpected_keys[:5]}")
    model.eval()

    merged = model.export_merged_state()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(merged, output)

    size_mb = output.stat().st_size / 1e6
    print(f"Merged checkpoint written: {output} ({size_mb:.0f} MB)")


if __name__ == "__main__":
    main()
