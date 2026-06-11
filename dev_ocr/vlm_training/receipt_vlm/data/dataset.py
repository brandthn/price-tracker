"""ReceiptDataset — torch Dataset over (image, canonical Ticket) pairs.

Each item is tokenized as ``prompt + canonical JSON + EOS``; labels mask the
prompt with ``-100`` so the loss only covers the JSON target. The 32-token
visual prefix is masked inside :meth:`ReceiptVLM.forward`, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, Union

import torch
from PIL import Image
from torch.utils.data import Dataset

from receipt_vlm.data.schema import Ticket, serialize_ticket

ImageSource = Union[str, Path, Image.Image, Callable[[], Image.Image]]


@dataclass
class ReceiptSample:
    """One training example: an image source and its canonical ground truth.

    ``image`` may be a path, PIL image, or a zero-arg callable returning PIL
    (used for on-the-fly synthetic rendering with layout/distortion variety).
    """

    image: ImageSource
    ticket: Ticket
    source: str = ""  # e.g. "synthetic", "cord", "sroie", "real"


def _load_image(source: ImageSource) -> Image.Image:
    if isinstance(source, Image.Image):
        return source
    if callable(source):
        return source()
    return Image.open(str(source))


class ReceiptDataset(Dataset):
    """Wraps heterogeneous receipt sources behind a single tensor interface.

    Args:
        samples: the (image, ticket) pairs.
        tokenizer: the SmolLM2 tokenizer (``pad_token`` must be set).
        transform: albumentations pipeline (train or eval variant).
        prompt: fixed instruction prepended to every target (must match the
            prompt used at inference by ``ReceiptVLM.generate``).
        max_length: hard cap on tokenized sequence length.
    """

    def __init__(
        self,
        samples: Sequence[ReceiptSample],
        tokenizer,
        transform,
        prompt: Optional[str] = None,
        max_length: int = 896,
    ) -> None:
        from receipt_vlm.models.vlm import SYSTEM_PROMPT

        self.samples = list(samples)
        self.tokenizer = tokenizer
        self.transform = transform
        self.prompt = prompt if prompt is not None else SYSTEM_PROMPT
        self.max_length = max_length
        self._prompt_ids = tokenizer(
            self.prompt, add_special_tokens=False
        ).input_ids

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        from receipt_vlm.data.augmentation import prepare_pixels

        sample = self.samples[index]
        image = _load_image(sample.image)
        pixels = prepare_pixels(image, self.transform)

        target = serialize_ticket(sample.ticket)
        target_ids = self.tokenizer(target, add_special_tokens=False).input_ids
        target_ids = target_ids + [self.tokenizer.eos_token_id]

        input_ids = (self._prompt_ids + target_ids)[: self.max_length]
        n_prompt = min(len(self._prompt_ids), len(input_ids))
        labels = [-100] * n_prompt + target_ids[: len(input_ids) - n_prompt]

        return {
            "pixel_values": torch.from_numpy(pixels),
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "target_text": target,
        }


def collate_receipts(batch: list[dict], pad_token_id: int) -> dict[str, torch.Tensor]:
    """Pad a batch to its longest sequence (right padding)."""
    max_len = max(item["input_ids"].shape[0] for item in batch)

    input_ids, labels, attention = [], [], []
    for item in batch:
        ids = item["input_ids"]
        pad = max_len - ids.shape[0]
        input_ids.append(
            torch.cat([ids, ids.new_full((pad,), pad_token_id)])
        )
        labels.append(
            torch.cat([item["labels"], item["labels"].new_full((pad,), -100)])
        )
        attention.append(
            torch.cat([torch.ones_like(ids), ids.new_zeros(pad)])
        )

    return {
        "pixel_values": torch.stack([item["pixel_values"] for item in batch]),
        "input_ids": torch.stack(input_ids),
        "labels": torch.stack(labels),
        "attention_mask": torch.stack(attention),
        "target_texts": [item["target_text"] for item in batch],
    }


def make_collate_fn(tokenizer) -> Callable[[list[dict]], dict[str, torch.Tensor]]:
    pad_id = tokenizer.pad_token_id
    return lambda batch: collate_receipts(batch, pad_id)
