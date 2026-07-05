"""From-scratch OCR vision encoder — CNN stem + multi-head transformer (no CLIP).

A small CNN stem downsamples the receipt image by 16x (cheap way to reach a text-legible
resolution on a T4), then a few multi-head self-attention layers give each spatial token global
context. Output is a flat ``(B, N, D)`` sequence of visual tokens the decoder cross-attends to.
Everything is a hand-rolled ``torch.nn`` module — no pretrained weights.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from receipt_vlm.data.ocr_transform import IMG_H, IMG_W


def _conv_block(in_ch: int, out_ch: int) -> nn.Sequential:
    """3x3 stride-2 conv (halves H,W) + GroupNorm + GELU."""
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, kernel_size=3, stride=2, padding=1),
        nn.GroupNorm(num_groups=min(8, out_ch), num_channels=out_ch),
        nn.GELU(),
    )


class OcrEncoder(nn.Module):
    """Image ``(B,3,H,W)`` -> visual tokens ``(B, (H/16)*(W/16), embed_dim)``."""

    STRIDE = 16  # total downsample of the stem (4 stride-2 blocks)

    def __init__(
        self,
        embed_dim: int = 256,
        depth: int = 4,
        num_heads: int = 8,
        img_h: int = IMG_H,
        img_w: int = IMG_W,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if img_h % self.STRIDE or img_w % self.STRIDE:
            raise ValueError(f"img size {img_h}x{img_w} must be divisible by {self.STRIDE}")
        self.grid_h, self.grid_w = img_h // self.STRIDE, img_w // self.STRIDE
        self.num_tokens = self.grid_h * self.grid_w
        self.embed_dim = embed_dim

        self.stem = nn.Sequential(
            _conv_block(3, embed_dim // 4),          # /2
            _conv_block(embed_dim // 4, embed_dim // 2),  # /4
            _conv_block(embed_dim // 2, embed_dim),  # /8
            _conv_block(embed_dim, embed_dim),       # /16
        )
        self.pos_embedding = nn.Parameter(torch.randn(1, self.num_tokens, embed_dim) * 0.02)

        layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=num_heads, dim_feedforward=embed_dim * 4,
            dropout=dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=depth, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(embed_dim)

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        feat = self.stem(pixel_values)              # (B, D, gh, gw)
        tokens = feat.flatten(2).transpose(1, 2)    # (B, gh*gw, D)
        tokens = tokens + self.pos_embedding
        tokens = self.transformer(tokens)
        return self.norm(tokens)                    # (B, N, D)
