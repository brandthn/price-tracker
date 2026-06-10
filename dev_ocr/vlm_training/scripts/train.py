"""Train one curriculum phase of the receipt VLM.

Usage:
    python scripts/train.py --config configs/phase1.yaml
    python scripts/train.py --config configs/phase2.yaml --resume checkpoints/phase1_best.pt
    python scripts/train.py --config configs/phase3.yaml --resume checkpoints/phase2_best.pt
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.dataset import ReceiptDataset, ReceiptSample, make_collate_fn  # noqa: E402


def load_config(phase_config_path: str) -> dict[str, Any]:
    """base.yaml overlaid with the phase file (one level deep merge)."""
    base_path = Path(phase_config_path).parent / "base.yaml"
    config: dict[str, Any] = {}
    if base_path.exists():
        config = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    phase = yaml.safe_load(Path(phase_config_path).read_text(encoding="utf-8")) or {}
    for key, value in phase.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def build_samples(config: dict[str, Any]) -> tuple[list[ReceiptSample], list[ReceiptSample]]:
    """Assemble train/val sample lists from the configured sources."""
    data_cfg = config["data"]
    sources = config["sources"]
    train: list[ReceiptSample] = []
    val: list[ReceiptSample] = []

    if "synthetic" in sources:
        from receipt_vlm.data.synthetic import load_dataset as load_synthetic

        pairs = load_synthetic(data_cfg["synthetic_dir"])
        if not pairs:
            raise FileNotFoundError(
                f"No synthetic data in {data_cfg['synthetic_dir']!r} — "
                "run scripts/generate_synthetic.py first."
            )
        samples = [
            ReceiptSample(image=path, ticket=ticket, source="synthetic")
            for path, ticket in pairs
        ]
        random.Random(0).shuffle(samples)
        limit = data_cfg.get("synthetic_limit")
        if limit:
            samples = samples[: int(limit)]
        n_val = max(1, int(len(samples) * data_cfg.get("synthetic_val_fraction", 0.05)))
        val.extend(samples[:n_val])
        train.extend(samples[n_val:])

    if "cord" in sources:
        from receipt_vlm.data.cord_adapter import load_cord_samples

        limit = data_cfg.get("cord_limit")
        train.extend(load_cord_samples("train", limit=limit))
        val.extend(load_cord_samples("validation", limit=64))

    if "sroie" in sources and data_cfg.get("sroie_dir"):
        from receipt_vlm.data.sroie_adapter import load_sroie_samples

        sroie = load_sroie_samples(data_cfg["sroie_dir"])
        cut = max(1, len(sroie) // 10)
        val.extend(sroie[:cut])
        train.extend(sroie[cut:])

    if "real" in sources:
        from receipt_vlm.data.real_photos import load_real_samples

        train.extend(load_real_samples(
            data_cfg["real_images_dir"], data_cfg["real_labels_dir"], split="train",
        ))
        val.extend(load_real_samples(
            data_cfg["real_images_dir"], data_cfg["real_labels_dir"], split="val",
        ))

    if not train:
        raise ValueError(f"No training samples for sources {sources!r}")
    return train, val


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="phase YAML config")
    parser.add_argument("--resume", help="checkpoint to resume from")
    args = parser.parse_args()

    config = load_config(args.config)
    print(f"Config: phase {config['phase']}, lr {config['lr']}, "
          f"epochs {config['epochs']}, sources {config['sources']}")

    from torch.utils.data import DataLoader

    from receipt_vlm.data.augmentation import build_eval_transform, build_train_augmentations
    from receipt_vlm.models.vlm import ReceiptVLM
    from receipt_vlm.training.trainer import ReceiptTrainer, load_model_state

    model_cfg = config.get("model", {})
    model = ReceiptVLM(
        lora_rank=model_cfg.get("lora_rank", 16),
        lora_alpha=model_cfg.get("lora_alpha", 32.0),
        lora_dropout=model_cfg.get("lora_dropout", 0.05),
    )
    if args.resume:
        load_model_state(model, args.resume)
        print(f"Resumed from {args.resume}")

    train_samples, val_samples = build_samples(config)
    print(f"Samples: {len(train_samples)} train / {len(val_samples)} val")

    train_dataset = ReceiptDataset(
        train_samples, model.tokenizer, build_train_augmentations(),
        max_length=config.get("max_length", 896),
    )
    val_dataset = ReceiptDataset(
        val_samples, model.tokenizer, build_eval_transform(),
        max_length=config.get("max_length", 896),
    )
    collate = make_collate_fn(model.tokenizer)
    train_loader = DataLoader(
        train_dataset, batch_size=config.get("batch_size", 8), shuffle=True,
        num_workers=config.get("num_workers", 2), collate_fn=collate,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=config.get("batch_size", 8), shuffle=False,
        num_workers=config.get("num_workers", 2), collate_fn=collate,
    )

    trainer = ReceiptTrainer(model, train_loader, val_loader, config)
    best = trainer.train_phase(
        phase=config["phase"],
        epochs=config["epochs"],
        lr=float(config["lr"]),
        trainable_patterns=tuple(config.get("trainable", ["projector", "lora_"])),
        weight_decay=config.get("weight_decay", 0.01),
        max_gen_samples=config.get("max_gen_samples", 16),
    )
    print(f"Best: {best}")


if __name__ == "__main__":
    main()
