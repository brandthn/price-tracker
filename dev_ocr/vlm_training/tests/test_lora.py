"""Tests for the hand-rolled LoRA implementation: shapes, zero-init delta, merge."""

import pytest

torch = pytest.importorskip("torch")
import torch.nn as nn  # noqa: E402

from receipt_vlm.models.lora import (  # noqa: E402
    LoRALinear,
    count_trainable_params,
    inject_lora,
    merge_lora,
)


def test_zero_init_delta() -> None:
    """At init the LoRA branch must be an exact no-op (B = 0)."""
    base = nn.Linear(64, 32)
    lora = LoRALinear(base, rank=8)
    lora.eval()
    x = torch.randn(4, 64)
    assert torch.allclose(lora(x), base(x), atol=1e-6)


def test_output_shape() -> None:
    base = nn.Linear(48, 96)
    lora = LoRALinear(base, rank=4)
    x = torch.randn(2, 10, 48)
    assert lora(x).shape == (2, 10, 96)


def test_original_frozen_adapters_trainable() -> None:
    lora = LoRALinear(nn.Linear(16, 16), rank=2)
    assert not lora.original.weight.requires_grad
    assert lora.lora_A.weight.requires_grad
    assert lora.lora_B.weight.requires_grad


def test_merge_correctness() -> None:
    """Merged linear must reproduce the adapted forward exactly."""
    base = nn.Linear(32, 24)
    lora = LoRALinear(base, rank=4, dropout=0.0)
    nn.init.normal_(lora.lora_B.weight, std=0.02)  # non-trivial delta
    lora.eval()

    merged = lora.merge_weights()
    x = torch.randn(8, 32)
    assert torch.allclose(lora(x), merged(x), atol=1e-5)


class _Block(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.q_proj = nn.Linear(16, 16)
        self.k_proj = nn.Linear(16, 16)
        self.v_proj = nn.Linear(16, 16)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.q_proj(x) + self.k_proj(x) + self.v_proj(x)


def test_inject_lora_targets_only() -> None:
    model = nn.Sequential(_Block(), _Block())
    inject_lora(model, rank=2)
    for block in model:
        assert isinstance(block.q_proj, LoRALinear)
        assert isinstance(block.v_proj, LoRALinear)
        assert isinstance(block.k_proj, nn.Linear)


def test_merge_lora_roundtrip() -> None:
    model = nn.Sequential(_Block())
    inject_lora(model, rank=2, dropout=0.0)
    nn.init.normal_(model[0].q_proj.lora_B.weight, std=0.02)
    model.eval()

    x = torch.randn(3, 16)
    before = model(x)
    merge_lora(model)
    assert isinstance(model[0].q_proj, nn.Linear)
    assert not isinstance(model[0].q_proj, LoRALinear)
    assert torch.allclose(model(x), before, atol=1e-5)


def test_count_trainable_params() -> None:
    model = nn.Sequential(_Block())
    inject_lora(model, rank=2)
    stats = count_trainable_params(model)
    assert stats["total"] == stats["trainable"] + stats["frozen"]
    # k_proj stays fully trainable; q/v originals frozen, adapters trainable.
    expected_trainable = (16 * 16 + 16) + 4 * (16 * 2)
    assert stats["trainable"] == expected_trainable
