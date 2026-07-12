"""Seq2seq dataset + collate for the OCR-VLM.

Each item: a receipt image -> pixel tensor (own OCR normalization) paired with the tokenized
linearized-schema target (``[BOS] ... [EOS]``). The collate pads targets to the batch max with
the tokenizer's PAD id (masked out of the loss). Reuses :class:`ReceiptSample` so synthetic
(live callables) and real (paths) sources share one interface.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import torch
from torch.utils.data import Dataset

from receipt_vlm.data.dataset import ReceiptSample, _load_image
from receipt_vlm.data.lin_schema import ticket_to_linear
from receipt_vlm.data.ocr_transform import IMG_H, IMG_W, prepare_ocr_pixels


class OcrDataset(Dataset):
    def __init__(
        self,
        samples: list[ReceiptSample],
        tokenizer: Any,
        img_h: int = IMG_H,
        img_w: int = IMG_W,
        max_len: int = 640,
        target_mode: str = "schema",
    ) -> None:
        if target_mode not in ("schema", "transcription"):
            raise ValueError(f"target_mode must be schema|transcription, got {target_mode!r}")
        self.samples = samples
        self.tokenizer = tokenizer
        self.img_h, self.img_w = img_h, img_w
        self.max_len = max_len
        self.target_mode = target_mode

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        sample = self.samples[idx]
        if self.target_mode == "transcription":
            # sample.image is a callable rendering (image, transcription) together, so the
            # target matches the exact pixels (Stage-A READ: image -> all visible text).
            image, target = sample.image()
        else:  # schema (Stage-B / M0): image -> linearized canonical schema
            image = _load_image(sample.image)
            target = ticket_to_linear(sample.ticket)
        pixels = prepare_ocr_pixels(image, self.img_h, self.img_w)
        ids = self.tokenizer.encode(target)[: self.max_len]
        if ids[-1] != self.tokenizer.eos_id:  # keep EOS after truncation
            ids[-1] = self.tokenizer.eos_id
        return torch.from_numpy(pixels), torch.tensor(ids, dtype=torch.long)


def make_ocr_collate(pad_id: int):
    """Collate fn: stack pixels, right-pad target ids to the batch max with ``pad_id``."""

    def collate(batch: list[tuple[torch.Tensor, torch.Tensor]]):
        pixels = torch.stack([b[0] for b in batch])
        max_t = max(b[1].size(0) for b in batch)
        ids = torch.full((len(batch), max_t), pad_id, dtype=torch.long)
        for i, (_, seq) in enumerate(batch):
            ids[i, : seq.size(0)] = seq
        return pixels, ids

    return collate
