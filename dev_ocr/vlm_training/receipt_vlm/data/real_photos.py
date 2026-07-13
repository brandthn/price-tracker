"""Chargeur des vraies photos de tickets du projet, et de leurs labels.

Les images sont dans dev_ocr/data/raw/images_tickets_caisse/. Les labels sont un JSON
canonique par image, plus un splits.json qui fige la partition train/val/test et un
review_status.json.

Le split de test ne contient que des labels relus a la main, et c'est verifie ici : un
pseudo-label non relu n'a rien a faire dans ce qui sert a mesurer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from receipt_vlm.data.dataset import ReceiptSample
from receipt_vlm.data.schema import ticket_from_dict

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

SPLITS_FILENAME = "splits.json"
REVIEW_FILENAME = "review_status.json"


def list_receipt_images(images_dir: str | Path) -> list[Path]:
    directory = Path(images_dir)
    return sorted(
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_real_samples(
    images_dir: str | Path,
    labels_dir: str | Path,
    split: Optional[str] = None,
    require_reviewed: Optional[bool] = None,
) -> list[ReceiptSample]:
    """Apparie les images avec leurs labels canoniques."""
    labels = Path(labels_dir)
    images = {p.name: p for p in list_receipt_images(images_dir)}

    selected = set(images)
    if split is not None:
        splits_path = labels / SPLITS_FILENAME
        if not splits_path.exists():
            raise FileNotFoundError(
                f"{splits_path} not found — run scripts/pseudo_label.py first."
            )
        splits = _load_json(splits_path)
        if split not in splits:
            raise KeyError(f"split {split!r} not in {sorted(splits)}")
        selected = set(splits[split]) & set(images)

    if require_reviewed is None:
        require_reviewed = split == "test"
    review: dict = {}
    review_path = labels / REVIEW_FILENAME
    if review_path.exists():
        review = _load_json(review_path)

    samples: list[ReceiptSample] = []
    for name in sorted(selected):
        label_path = labels / (Path(name).stem + ".json")
        if not label_path.exists():
            continue
        if require_reviewed and not review.get(name, {}).get("reviewed", False):
            continue
        ticket = ticket_from_dict(_load_json(label_path))
        samples.append(ReceiptSample(image=images[name], ticket=ticket, source="real"))
    return samples


def freeze_splits(
    image_names: list[str],
    labels_dir: str | Path,
    test_fraction: float = 0.3,
    val_fraction: float = 0.15,
    seed: int = 1234,
) -> dict[str, list[str]]:
    """Fige une partition train/val/test, et l'ecrit sur disque.

    Refuse d'ecraser un splits.json existant : le jeu de test doit rester fige,
    stay frozen once created.
    """
    import random

    splits_path = Path(labels_dir) / SPLITS_FILENAME
    if splits_path.exists():
        raise FileExistsError(f"{splits_path} already exists — splits are frozen.")

    names = sorted(image_names)
    random.Random(seed).shuffle(names)
    n_test = max(1, round(len(names) * test_fraction))
    n_val = max(1, round(len(names) * val_fraction))
    splits = {
        "test": sorted(names[:n_test]),
        "val": sorted(names[n_test : n_test + n_val]),
        "train": sorted(names[n_test + n_val :]),
    }
    splits_path.write_text(
        json.dumps(splits, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return splits
