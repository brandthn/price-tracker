"""L'OCR-VLM : encodeur + decodeur, sans CLIP ni LLM pre-entraine.

Image -> OcrEncoder -> tokens visuels -> OcrDecoder -> sequence du schema linearise
-> linear_to_ticket -> Ticket canonique.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from receipt_vlm.data.lin_schema import linear_to_ticket
from receipt_vlm.data.ocr_transform import IMG_H, IMG_W
from receipt_vlm.data.schema import Ticket
from receipt_vlm.models.ocr_decoder import OcrDecoder
from receipt_vlm.models.ocr_encoder import OcrEncoder


class OcrVLM(nn.Module):
    def __init__(
        self,
        tokenizer: Any,                 # CharTokenizer, garde en attribut et pas en sous-module
        embed_dim: int = 256,
        enc_depth: int = 4,
        dec_depth: int = 4,
        num_heads: int = 8,
        img_h: int = IMG_H,
        img_w: int = IMG_W,
        max_len: int = 640,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.tokenizer = tokenizer
        self.pad_id = tokenizer.pad_id
        self.bos_id = tokenizer.bos_id
        self.eos_id = tokenizer.eos_id
        self.max_len = max_len
        self.config: dict[str, Any] = {
            "embed_dim": embed_dim, "enc_depth": enc_depth, "dec_depth": dec_depth,
            "num_heads": num_heads, "img_h": img_h, "img_w": img_w, "max_len": max_len,
            "dropout": dropout,
        }

        self.encoder = OcrEncoder(embed_dim, enc_depth, num_heads, img_h, img_w, dropout)
        self.decoder = OcrDecoder(
            tokenizer.vocab_size, embed_dim, dec_depth, num_heads, max_len, self.pad_id, dropout
        )

    def forward(
        self, pixel_values: torch.Tensor, target_ids: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Teacher-forced pass. ``target_ids`` = full BOS..EOS sequence (B, T)."""
        memory = self.encoder(pixel_values)
        inp, gold = target_ids[:, :-1], target_ids[:, 1:]
        logits = self.decoder(inp, memory, tgt_key_padding_mask=inp.eq(self.pad_id))
        loss = F.cross_entropy(
            logits.reshape(-1, logits.size(-1)), gold.reshape(-1), ignore_index=self.pad_id
        )
        return logits, loss

    @torch.no_grad()
    def generate(
        self, pixel_values: torch.Tensor, max_len: int | None = None, return_text: bool = False
    ):
        """Greedy autoregressive decode -> list[Ticket] (or list[str] if return_text)."""
        self.eval()
        max_len = max_len or self.max_len
        memory = self.encoder(pixel_values)
        device = pixel_values.device
        batch = pixel_values.size(0)

        ids = torch.full((batch, 1), self.bos_id, dtype=torch.long, device=device)
        done = torch.zeros(batch, dtype=torch.bool, device=device)
        for _ in range(max_len - 1):
            logits = self.decoder(ids, memory)         # (B, t, V)
            nxt = logits[:, -1].argmax(-1)             # (B,)
            nxt = torch.where(done, torch.full_like(nxt, self.pad_id), nxt)
            ids = torch.cat([ids, nxt.unsqueeze(1)], dim=1)
            done |= nxt.eq(self.eos_id)
            if bool(done.all()):
                break

        texts = [self.tokenizer.decode(row) for row in ids.tolist()]
        if return_text:
            return texts
        return [linear_to_ticket(t) for t in texts]

    def save(self, path: str) -> None:
        torch.save({"model_state": self.state_dict(), "config": self.config}, path)

    @classmethod
    def from_checkpoint(cls, path: str, tokenizer: Any, device: str = "cpu") -> "OcrVLM":
        ckpt = torch.load(path, map_location=device, weights_only=False)
        model = cls(tokenizer, **ckpt["config"])
        model.load_state_dict(ckpt["model_state"])
        return model.to(device).eval()
