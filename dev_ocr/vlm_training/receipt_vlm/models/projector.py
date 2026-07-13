"""Le projecteur multimodal : la piece qu'on entraine vraiment.

Il envoie les patchs de CLIP (gele) dans l'espace d'embedding de SmolLM2 (gele), par
cross-attention avec des query tokens appris, plus un resume MLP residuel. C'est
l'unique passerelle entre les deux moities du modele.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class MultimodalProjector(nn.Module):
    """Envoie les patchs de CLIP dans l'espace d'embedding du modele de langue."""

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
        """Project patch embeddings to LM space."""
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
