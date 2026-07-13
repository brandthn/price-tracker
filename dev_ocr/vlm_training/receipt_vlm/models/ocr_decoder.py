"""Decodeur autoregressif de l'OCR-VLM.

Un petit transformer qui fait de la cross-attention sur les tokens visuels de
l'encodeur et sort la sequence du schema linearise. Teacher forcing a l'entrainement,
decodage glouton a la generation.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class OcrDecoder(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        embed_dim: int = 256,
        depth: int = 4,
        num_heads: int = 8,
        max_len: int = 640,
        pad_id: int = 0,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.max_len = max_len
        self.token_embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=pad_id)
        self.pos_embedding = nn.Parameter(torch.randn(1, max_len, embed_dim) * 0.02)

        layer = nn.TransformerDecoderLayer(
            d_model=embed_dim, nhead=num_heads, dim_feedforward=embed_dim * 4,
            dropout=dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerDecoder(layer, num_layers=depth)
        self.norm = nn.LayerNorm(embed_dim)
        self.head = nn.Linear(embed_dim, vocab_size)

    def forward(
        self,
        tgt_ids: torch.Tensor,          # (B, T) input tokens (teacher forcing)
        memory: torch.Tensor,           # (B, N, D) encoder tokens
        tgt_key_padding_mask: torch.Tensor | None = None,  # (B, T) True where PAD
    ) -> torch.Tensor:
        T = tgt_ids.size(1)
        x = self.token_embedding(tgt_ids) + self.pos_embedding[:, :T]
        # Masque causal en booleen (True = masque). Les deux masques en bool, sinon
        # torch rale sur les types melanges.
        causal = torch.ones(T, T, dtype=torch.bool, device=tgt_ids.device).triu(1)
        h = self.transformer(
            x, memory, tgt_mask=causal, tgt_key_padding_mask=tgt_key_padding_mask
        )
        return self.head(self.norm(h))  # (B, T, vocab)
