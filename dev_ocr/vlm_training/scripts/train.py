"""Joue une phase du curriculum du modele hybride (CLIP + SmolLM2 + LoRA).

Attention : ce script n'entraine PAS l'OCR-VLM maison, qui a sa propre boucle dans
train_ocr_vlm.py.

    python scripts/train.py --config configs/phase1.yaml
    python scripts/train.py --config configs/phase2.yaml --resume checkpoints/phase1_best.pt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.dataset import ReceiptDataset, make_collate_fn  # noqa: E402
from receipt_vlm.data.samples import build_samples  # noqa: E402


def _epoch_num(path: Path) -> int:
    """Epoch index embedded in a ``phase{p}_epoch{NN}_loss{L}.pt`` filename."""
    match = re.search(r"_epoch(\d+)_", path.name)
    return int(match.group(1)) if match else -1


def _epoch_ckpts(checkpoint_dir: Path, phase: int) -> list[Path]:
    """Per-epoch snapshots for ``phase``, sorted oldest -> newest."""
    return sorted(checkpoint_dir.glob(f"phase{phase}_epoch*.pt"), key=_epoch_num)


def resolve_resume(
    checkpoint_dir: str | Path, phase: int, explicit: str | None
) -> tuple[str | None, int]:
    """Pick the checkpoint to resume from and the epoch to continue at.

    Precedence:
      1. **Mid-phase recovery** — the latest ``phase{p}_epoch*.pt`` for *this* phase;
         training continues right after that epoch.
      2. An explicit ``--resume`` path (back-compat with the other notebooks).
      3. **Start of phase** — the *last* checkpoint of the previous phase (its highest
         epoch snapshot, else its legacy ``phase{p-1}_best.pt``); training starts at epoch 0.
    """
    checkpoint_dir = Path(checkpoint_dir)
    same_phase = _epoch_ckpts(checkpoint_dir, phase)
    if same_phase:
        latest = same_phase[-1]
        return str(latest), _epoch_num(latest)
    if explicit:
        return explicit, 0
    if phase > 1:
        prev = _epoch_ckpts(checkpoint_dir, phase - 1)
        if prev:
            return str(prev[-1]), 0
        legacy = checkpoint_dir / f"phase{phase - 1}_best.pt"
        if legacy.is_file():
            return str(legacy), 0
    return None, 0


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
    parser.add_argument("--config", required=True, help="le YAML de la phase")
    parser.add_argument("--resume", help="checkpoint depuis lequel reprendre")
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
    resume_path, start_epoch = resolve_resume(
        config.get("checkpoint_dir", "checkpoints"), config["phase"], args.resume
    )
    if resume_path:
        load_model_state(model, resume_path)
        print(f"Resumed from {resume_path} (continue at epoch {start_epoch + 1})", flush=True)

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
        start_epoch=start_epoch,
    )
    print(f"Best: {best}", flush=True)


if __name__ == "__main__":
    main()
