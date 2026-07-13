"""LoRA ecrit a la main, sans dependre de peft.

W*x devient W*x + (B @ A)*x * (alpha/rank), avec A et B deux petites matrices
entrainables et W gele (Hu et al., 2021).
"""

from __future__ import annotations

import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    """Enveloppe LoRA autour d'un nn.Linear gele.

    Replaces ``W*x`` with ``W*x + (B @ A)*x * (alpha/rank)``.
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

        # A tire au hasard, B a zero : au depart l'adaptateur ne change donc rien.
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
    """Remplace recursivement les nn.Linear vises par des LoRALinear.

    Modifie le modele en place, et le rend pour pouvoir chainer.
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
    """Refond chaque LoRALinear dans un nn.Linear classique, pour l'inference.

    L'inverse d'inject_lora. Sert a l'export, pour que l'inference charge un modele
    ordinaire, sans adaptateur.
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
