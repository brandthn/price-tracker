"""Multimodal projector — the core from-scratch contribution.

Maps frozen CLIP patch embeddings into the SmolLM2 token embedding space using
cross-attention with learned query tokens (Q-Former-lite) plus a residual MLP
summary. No pretrained weights.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class MultimodalProjector(nn.Module):
    """Project CLIP patch embeddings into the language model embedding space.

    Args:
        vision_dim: CLIP output dim (768 for ViT-B/16).
        lang_dim: LM hidden dim (960 for SmolLM2-360M).
        num_patches: number of visual tokens (197 for ViT-B/16 @ 224px + CLS).
        num_queries: number of learned summary tokens emitted to the LM.
        num_heads: attention heads in the cross-attention.
        dropout: dropout rate.
    """

    def __init__(
        self,
        vision_dim: int = 768,
        lang_dim: int = 960,
        num_patches: int = 197,
        num_queries: int = 32,
        num_heads: int = 8,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.vision_dim = vision_dim
        self.lang_dim = lang_dim
        self.num_queries = num_queries

        # Learnable positional encoding for visual patches.
        self.pos_embedding = nn.Parameter(
            torch.randn(1, num_patches, vision_dim) * 0.02
        )

        # Learnable visual summary tokens (queries of the cross-attention).
        self.query_tokens = nn.Parameter(
            torch.randn(1, num_queries, lang_dim) * 0.02
        )

        # Cross-attention: language-space queries attend to visual keys/values.
        self.cross_attn = nn.MultiheadAttention(
            embed_dim=lang_dim,
            num_heads=num_heads,
            kdim=vision_dim,
            vdim=vision_dim,
            dropout=dropout,
            batch_first=True,
        )

        # Patch-level MLP projection, mean-pooled into a residual summary.
        self.mlp = nn.Sequential(
            nn.Linear(vision_dim, lang_dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(lang_dim * 2, lang_dim),
        )
        self.norm1 = nn.LayerNorm(lang_dim)
        self.norm2 = nn.LayerNorm(lang_dim)

        self._init_weights()

    def _init_weights(self) -> None:
        for module in self.mlp.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, vision_features: torch.Tensor) -> torch.Tensor:
        """Project patch embeddings to LM space.

        Args:
            vision_features: ``(B, num_patches, vision_dim)`` from CLIP.

        Returns:
            ``(B, num_queries, lang_dim)`` visual tokens in LM embedding space.
        """
        batch = vision_features.shape[0]

        vision_features = vision_features + self.pos_embedding

        queries = self.query_tokens.expand(batch, -1, -1)

        attended, _ = self.cross_attn(
            query=queries,
            key=vision_features,
            value=vision_features,
        )
        attended = self.norm1(attended)

        patch_proj = self.mlp(vision_features)
        patch_summary = patch_proj.mean(dim=1, keepdim=True)

        return self.norm2(attended + patch_summary)
