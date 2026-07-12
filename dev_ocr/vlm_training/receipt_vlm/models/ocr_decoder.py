"""From-scratch autoregressive decoder for the OCR-VLM.

A small transformer decoder that cross-attends to the encoder's visual tokens and emits the
linearized-schema token sequence (see :mod:`receipt_vlm.data.lin_schema`). Hand-rolled
``torch.nn`` — no pretrained language model. Teacher-forced at train time; greedy at generate
time (driven from :class:`receipt_vlm.models.ocr_vlm.OcrVLM`).
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
        # Bool causal mask (True = masked); bool for both masks avoids the mixed-type warning.
        causal = torch.ones(T, T, dtype=torch.bool, device=tgt_ids.device).triu(1)
        h = self.transformer(
            x, memory, tgt_mask=causal, tgt_key_padding_mask=tgt_key_padding_mask
        )
        return self.head(self.norm(h))  # (B, T, vocab)
