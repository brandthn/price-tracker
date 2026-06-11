"""Train one curriculum phase of the receipt VLM.

Usage:
    python scripts/train.py --config configs/phase1.yaml
    python scripts/train.py --config configs/phase1_colab.yaml
    python scripts/train.py --config configs/phase2_colab.yaml --resume /content/drive/MyDrive/receipt_vlm/checkpoints/phase1_best.pt
    python scripts/train.py --config configs/phase3.yaml --resume checkpoints/phase2_best.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.dataset import ReceiptDataset, make_collate_fn  # noqa: E402
from receipt_vlm.data.samples import build_samples  # noqa: E402


def _merge_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """One-level-deep dict merge (``overlay`` wins on scalar keys)."""
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def load_config(phase_config_path: str) -> dict[str, Any]:
    """Merge ``base.yaml`` [+ ``colab_paths.yaml``] + phase file."""
    config_dir = Path(phase_config_path).parent
    config: dict[str, Any] = {}
    if (config_dir / "base.yaml").exists():
        config = yaml.safe_load((config_dir / "base.yaml").read_text(encoding="utf-8")) or {}

    phase_name = Path(phase_config_path).name
    if "_colab" in phase_name and (config_dir / "colab_paths.yaml").exists():
        colab = yaml.safe_load((config_dir / "colab_paths.yaml").read_text(encoding="utf-8")) or {}
        config = _merge_config(config, colab)

    phase = yaml.safe_load(Path(phase_config_path).read_text(encoding="utf-8")) or {}
    config = _merge_config(config, phase)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="phase YAML config")
    parser.add_argument("--resume", help="checkpoint to resume from")
    args = parser.parse_args()

    config = load_config(args.config)
    print(
        f"Config: phase {config['phase']}, lr {config['lr']}, "
        f"epochs {config['epochs']}, sources {config['sources']}",
        flush=True,
    )

    from torch.utils.data import DataLoader

    from receipt_vlm.data.augmentation import build_eval_transform, build_train_augmentations
    from receipt_vlm.models.vlm import ReceiptVLM
    from receipt_vlm.training.trainer import ReceiptTrainer, load_model_state

    model_cfg = config.get("model", {})
    model = ReceiptVLM(
        lora_rank=model_cfg.get("lora_rank", 16),
        lora_alpha=model_cfg.get("lora_alpha", 32.0),
        lora_dropout=model_cfg.get("lora_dropout", 0.05),
        gradient_checkpointing=bool(model_cfg.get("gradient_checkpointing", False)),
    )
    if args.resume:
        load_model_state(model, args.resume)
        print(f"Resumed from {args.resume}", flush=True)

    train_samples, val_samples = build_samples(config)
    print(f"Samples: {len(train_samples)} train / {len(val_samples)} val", flush=True)

    train_dataset = ReceiptDataset(
        train_samples,
        model.tokenizer,
        build_train_augmentations(),
        max_length=config.get("max_length", 896),
    )
    val_dataset = ReceiptDataset(
        val_samples,
        model.tokenizer,
        build_eval_transform(),
        max_length=config.get("max_length", 896),
    )
    collate = make_collate_fn(model.tokenizer)
    train_loader = DataLoader(
        train_dataset,
        batch_size=config.get("batch_size", 8),
        shuffle=True,
        num_workers=config.get("num_workers", 2),
        collate_fn=collate,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=config.get("batch_size", 8),
        shuffle=False,
        num_workers=config.get("num_workers", 2),
        collate_fn=collate,
    )

    trainer = ReceiptTrainer(model, train_loader, val_loader, config)
    best = trainer.train_phase(
        phase=config["phase"],
        epochs=config["epochs"],
        lr=float(config["lr"]),
        trainable_patterns=tuple(config.get("trainable", ["projector", "lora_"])),
        weight_decay=config.get("weight_decay", 0.01),
        max_gen_samples=config.get("max_gen_samples", 16),
        log_every=int(config.get("log_every", 0)),
    )
    print(f"Best: {best}", flush=True)


if __name__ == "__main__":
    main()
