"""Hand-rolled 3-phase training loop — no HuggingFace Trainer.

Phases (adapted spec §6):
    1. Projector warmup     — projector only, CORD+SROIE+synthetic
    2. LoRA fine-tuning     — projector + LoRA, all sources
    3. JSON alignment       — projector + LoRA, low LR, real photos + synthetic
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

from receipt_vlm.data.schema import Ticket, ticket_from_json
from receipt_vlm.utils.metrics import evaluate_tickets


class ReceiptTrainer:
    """Raw-PyTorch trainer with mixed precision, clipping and best-val checkpoints.

    Args:
        model: a :class:`~receipt_vlm.models.vlm.ReceiptVLM`.
        train_loader / val_loader: dataloaders yielding the dict batches
            produced by :func:`receipt_vlm.data.dataset.collate_receipts`.
        config: arbitrary config dict; must contain ``checkpoint_dir``.
    """

    def __init__(
        self,
        model: nn.Module,
        train_loader: DataLoader,
        val_loader: DataLoader,
        config: dict[str, Any],
    ) -> None:
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.use_bf16 = (
            self.device.type == "cuda" and torch.cuda.is_bf16_supported()
        )
        self.amp_dtype = torch.bfloat16 if self.use_bf16 else torch.float16
        # GradScaler is only needed for fp16 (bf16 has enough dynamic range).
        self.scaler = torch.amp.GradScaler(
            enabled=self.device.type == "cuda" and not self.use_bf16
        )
        self.model.to(self.device)

    # ------------------------------------------------------------------

    def train_phase(
        self,
        phase: int,
        epochs: int,
        lr: float,
        trainable_patterns: tuple[str, ...] = ("projector", "lora_"),
        weight_decay: float = 0.01,
        max_gen_samples: int = 16,
        log_every: int = 0,
        start_epoch: int = 0,
    ) -> dict[str, Any]:
        """Run one curriculum phase; returns the best validation record.

        Each epoch writes two checkpoints: ``phase{p}_best.pt`` (overwritten on
        improvement, used by export) and a per-epoch ``phase{p}_epoch{NN}_loss{L}.pt``
        snapshot so a mid-phase stop loses at most the current epoch. ``start_epoch``
        resumes the loop part-way through a phase (see ``scripts/train.py`` auto-resume);
        optimizer momentum is not restored — adapter-only checkpoints stay small — but the
        cosine LR schedule is fast-forwarded so the learning-rate curve still lines up.
        """
        self._set_trainable(trainable_patterns)
        trainable = [p for p in self.model.parameters() if p.requires_grad]
        if not trainable:
            raise ValueError(f"no trainable parameters match {trainable_patterns}")
        print(
            f"Phase {phase}: {sum(p.numel() for p in trainable):,} trainable params "
            f"(patterns: {', '.join(trainable_patterns)})"
        )

        optimizer = AdamW(trainable, lr=lr, weight_decay=weight_decay)
        scheduler = CosineAnnealingLR(optimizer, T_max=epochs)
        if start_epoch:
            if start_epoch >= epochs:
                print(f"Phase {phase} already complete ({start_epoch}/{epochs} epochs)", flush=True)
                return {"val_loss": float("inf"), "phase": phase, "epoch": start_epoch}
            for _ in range(start_epoch):  # align the LR schedule with resumed progress
                scheduler.step()
            print(f"Resuming phase {phase} at epoch {start_epoch + 1}/{epochs}", flush=True)

        best: dict[str, Any] = {"val_loss": float("inf")}
        for epoch in range(start_epoch, epochs):
            start = time.time()
            train_loss = self._train_epoch(optimizer, log_every=log_every)
            val_loss, val_metrics = self._val_epoch(max_gen_samples)
            scheduler.step()

            elapsed = time.time() - start
            f1 = val_metrics.get("field_f1", float("nan"))
            print(
                f"Phase {phase} | Epoch {epoch + 1}/{epochs} | "
                f"train {train_loss:.4f} | val {val_loss:.4f} | "
                f"F1 {f1:.3f} | {elapsed:.0f}s"
            )

            record = {
                "phase": phase,
                "epoch": epoch + 1,
                "val_loss": val_loss,
                **val_metrics,
            }
            if val_loss < best["val_loss"]:
                best = record
                self._save_checkpoint(f"phase{phase}_best.pt", best)
            # Per-epoch snapshot LAST so a stdout-watching notebook can mirror both
            # files to durable storage when it sees this "_epoch" save line.
            self._save_checkpoint(
                f"phase{phase}_epoch{epoch + 1:02d}_loss{val_loss:.4f}.pt", record
            )
        return best

    # ------------------------------------------------------------------

    def _set_trainable(self, patterns: tuple[str, ...]) -> None:
        for name, param in self.model.named_parameters():
            param.requires_grad = any(pattern in name for pattern in patterns)

    def _autocast(self):
        return torch.autocast(
            device_type=self.device.type,
            dtype=self.amp_dtype,
            enabled=self.device.type == "cuda",
        )

    def _train_epoch(self, optimizer: torch.optim.Optimizer, log_every: int = 0) -> float:
        self.model.train()
        total_loss, n_batches = 0.0, 0
        n_total = len(self.train_loader)
        for batch in self.train_loader:
            pixel_values = batch["pixel_values"].to(self.device)
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            labels = batch["labels"].to(self.device)

            optimizer.zero_grad(set_to_none=True)
            with self._autocast():
                _, loss = self.model(
                    pixel_values, input_ids,
                    attention_mask=attention_mask, labels=labels,
                )

            self.scaler.scale(loss).backward()
            self.scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(
                [p for p in self.model.parameters() if p.requires_grad], 1.0
            )
            self.scaler.step(optimizer)
            self.scaler.update()

            total_loss += loss.item()
            n_batches += 1
            if log_every and n_batches % log_every == 0:
                print(
                    f"  batch {n_batches}/{n_total} loss {loss.item():.4f}",
                    flush=True,
                )
        return total_loss / max(1, n_batches)

    @torch.no_grad()
    def _val_epoch(self, max_gen_samples: int) -> tuple[float, dict[str, float]]:
        self.model.eval()
        total_loss, n_batches = 0.0, 0
        predictions: list[Ticket] = []
        golds: list[Ticket] = []

        for batch in self.val_loader:
            pixel_values = batch["pixel_values"].to(self.device)
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            labels = batch["labels"].to(self.device)

            with self._autocast():
                _, loss = self.model(
                    pixel_values, input_ids,
                    attention_mask=attention_mask, labels=labels,
                )
            total_loss += loss.item()
            n_batches += 1

            # Generation-based metrics on a budget (constrained decoding is
            # sequential and would dominate epoch time otherwise). Set
            # max_gen_samples=0 in config to skip entirely (recommended phase 1).
            if max_gen_samples <= 0:
                continue
            remaining = max_gen_samples - len(predictions)
            if remaining > 0:
                # Generation must run under the SAME autocast as the training
                # forward. AMP caches bf16 copies of the autocast-eligible
                # weights (the LoRA-wrapped q_proj/v_proj); calling generate()
                # outside autocast feeds an fp32 input into a bf16 weight and
                # raises "mat1 and mat2 have different dtype". Disabled on CPU.
                with self._autocast():
                    outputs = self.model.generate(
                        pixel_values[:remaining], constrained=True
                    )
                for output, target in zip(outputs, batch["target_texts"]):
                    predictions.append(ticket_from_json(output))
                    golds.append(ticket_from_json(target))

        metrics = evaluate_tickets(predictions, golds) if predictions else {}
        return total_loss / max(1, n_batches), metrics

    @staticmethod
    def _is_adapter_key(key: str) -> bool:
        """True for the only tensors we actually train.

        The from-scratch projector and the LoRA adapters are the sole trained
        weights; the frozen CLIP + SmolLM2 backbones are re-created identically
        from their pretrained init on every ``ReceiptVLM(...)``. Persisting them
        would bloat each checkpoint to ~1.8 GB and make Colab-disk saves and
        browser transfers corruption-prone. Adapter-only is ~11M params (~45 MB).
        """
        return key.startswith("projector.") or "lora_A" in key or "lora_B" in key

    def _save_checkpoint(self, name: str, record: dict[str, Any]) -> None:
        import os

        checkpoint_dir = Path(self.config.get("checkpoint_dir", "checkpoints"))
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        path = checkpoint_dir / name

        adapter_state = {
            k: v for k, v in self.model.state_dict().items() if self._is_adapter_key(k)
        }
        payload = {
            "model_state": adapter_state,
            "config": self.config,
            "record": record,
            "adapter_only": True,
        }

        # Atomic write + read-back verify: a truncated checkpoint (full disk,
        # killed process, bad transfer) must fail loudly HERE, not hours later
        # when a downstream phase tries to resume from it.
        tmp = path.with_name(path.name + ".tmp")
        torch.save(payload, tmp)
        try:
            torch.load(tmp, map_location="cpu", weights_only=False)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"checkpoint verify failed for {path}: {exc}") from exc
        os.replace(tmp, path)

        (checkpoint_dir / (path.stem + ".json")).write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(f"Checkpoint saved: {path} ({path.stat().st_size / 1e6:.0f} MB, adapter-only)")


def load_model_state(model: nn.Module, checkpoint_path: str | Path) -> None:
    """Load a training checkpoint produced by :class:`ReceiptTrainer`.

    Checkpoints store only the trained projector + LoRA tensors; the frozen
    backbones already exist from the pretrained init, so the load is non-strict
    (missing backbone keys are expected). Legacy full checkpoints still load.
    """
    checkpoint = torch.load(
        str(checkpoint_path), map_location="cpu", weights_only=False
    )
    state = checkpoint["model_state"]
    result = model.load_state_dict(state, strict=False)
    if result.unexpected_keys:
        raise RuntimeError(
            f"unexpected keys in {checkpoint_path}: {result.unexpected_keys[:5]}"
        )
    print(
        f"Loaded {len(state)} adapter/projector tensors from "
        f"{Path(checkpoint_path).name}",
        flush=True,
    )
