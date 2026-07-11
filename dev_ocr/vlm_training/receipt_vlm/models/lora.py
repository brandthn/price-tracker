"""Hand-rolled LoRA adapters — no ``peft`` dependency.

Implements Low-Rank Adaptation (Hu et al., 2021) from scratch:
``W*x`` becomes ``W*x + (B @ A)*x * (alpha/rank)`` where ``A`` and ``B`` are
small trainable matrices and ``W`` stays frozen.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    """Low-Rank Adaptation wrapper around a frozen ``nn.Linear``.

    Replaces ``W*x`` with ``W*x + (B @ A)*x * (alpha/rank)``.

    Args:
        original: the pretrained linear layer to adapt (frozen in place).
        rank: bottleneck dimension of the low-rank decomposition.
        alpha: scaling numerator; effective scale is ``alpha / rank``.
        dropout: dropout applied to the LoRA branch input.
    """

    def __init__(
        self,
        original: nn.Linear,
        rank: int = 16,
        alpha: float = 32.0,
        dropout: float = 0.05,
    ) -> None:
        super().__init__()
        self.original = original
        self.rank = rank
        self.alpha = alpha
        self.scale = alpha / rank

        for param in self.original.parameters():
            param.requires_grad = False

        d_out, d_in = original.weight.shape
        self.lora_A = nn.Linear(d_in, rank, bias=False)
        self.lora_B = nn.Linear(rank, d_out, bias=False)
        self.dropout = nn.Dropout(dropout)

        # A ~ N(0, 0.02), B = 0 → the adapter starts as an exact identity delta.
        nn.init.normal_(self.lora_A.weight, std=0.02)
        nn.init.zeros_(self.lora_B.weight)

    @property
    def in_features(self) -> int:
        return self.original.in_features

    @property
    def out_features(self) -> int:
        return self.original.out_features

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        original_out = self.original(x)
        lora_out = self.lora_B(self.lora_A(self.dropout(x)))
        return original_out + self.scale * lora_out

    @torch.no_grad()
    def merge_weights(self) -> nn.Linear:
        """Fold the LoRA delta into the base weights for zero-overhead inference."""
        merged = nn.Linear(
            self.original.in_features,
            self.original.out_features,
            bias=self.original.bias is not None,
        )
        merged.weight.data = (
            self.original.weight.data
            + self.scale * (self.lora_B.weight @ self.lora_A.weight)
        ).to(self.original.weight.dtype)
        if self.original.bias is not None:
            merged.bias.data = self.original.bias.data.clone()
        return merged


def inject_lora(
    model: nn.Module,
    rank: int = 16,
    alpha: float = 32.0,
    dropout: float = 0.05,
    target_modules: tuple[str, ...] = ("q_proj", "v_proj"),
) -> nn.Module:
    """Recursively replace target ``nn.Linear`` layers with :class:`LoRALinear`.

    Mutates ``model`` in place and returns it for chaining.
    """
    for name, module in model.named_children():
        if isinstance(module, nn.Linear) and name in target_modules:
            setattr(
                model,
                name,
                LoRALinear(module, rank=rank, alpha=alpha, dropout=dropout),
            )
        else:
            inject_lora(module, rank=rank, alpha=alpha, dropout=dropout,
                        target_modules=target_modules)
    return model


def merge_lora(model: nn.Module) -> nn.Module:
    """Recursively replace every :class:`LoRALinear` with its merged ``nn.Linear``.

    Inverse of :func:`inject_lora`; used by the checkpoint export script so the
    runtime provider loads a plain (adapter-free) model.
    """
    for name, module in model.named_children():
        if isinstance(module, LoRALinear):
            setattr(model, name, module.merge_weights())
        else:
            merge_lora(module)
    return model


def count_trainable_params(model: nn.Module) -> dict[str, float]:
    """Report total / trainable / frozen parameter counts."""
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return {
        "total": total,
        "trainable": trainable,
        "frozen": total - trainable,
        "trainable_pct": 100.0 * trainable / total if total else 0.0,
    }
