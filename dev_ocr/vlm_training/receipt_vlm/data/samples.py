"""Construction des listes d'echantillons d'entrainement a partir de la config."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from receipt_vlm.data.dataset import ReceiptSample
from receipt_vlm.data.schema import Ticket


def _live_render_factory(
    seed: int,
    ticket: Ticket,
    *,
    diverse: bool,
    distort: bool,
    distort_intensity: str,
):
    """Rend un callable sans argument, qui dessine le ticket avec son bruit."""

    def render() -> "Image.Image":
        from receipt_vlm.data.synthetic import render_receipt_image

        return render_receipt_image(
            ticket,
            seed=seed,
            diverse=diverse,
            distort=distort,
            distort_intensity=distort_intensity,
        )

    return render


def build_live_synthetic_samples(
    count: int,
    seed: int = 0,
    *,
    diverse: bool = True,
    distort: bool = True,
    distort_intensity: str = "medium",
) -> list[ReceiptSample]:
    """Synthetique genere a la volee : aucun PNG sur le disque, et une mise en page
    differente a chaque epoch."""
    from receipt_vlm.data.synthetic import generate_ticket

    samples: list[ReceiptSample] = []
    for i in range(count):
        s = seed + i
        ticket = generate_ticket(seed=s)
        samples.append(
            ReceiptSample(
                image=_live_render_factory(
                    s,
                    ticket,
                    diverse=diverse,
                    distort=distort,
                    distort_intensity=distort_intensity,
                ),
                ticket=ticket,
                source="synthetic_live",
            )
        )
    return samples


def load_disk_synthetic_samples(
    directory: str | Path,
    *,
    diverse: bool = False,
    distort: bool = False,
    distort_intensity: str = "medium",
) -> list[ReceiptSample]:
    """Charge les paires PNG+JSON deja ecrites sur le disque."""
    from receipt_vlm.data.synthetic import load_dataset as load_synthetic

    pairs = load_synthetic(directory)
    samples: list[ReceiptSample] = []
    for path, ticket in pairs:
        if diverse or distort:
            stem = path.stem
            try:
                render_seed = int(stem.split("_")[-1])
            except ValueError:
                render_seed = hash(stem) & 0xFFFF
            samples.append(
                ReceiptSample(
                    image=_live_render_factory(
                        render_seed,
                        ticket,
                        diverse=diverse,
                        distort=distort,
                        distort_intensity=distort_intensity,
                    ),
                    ticket=ticket,
                    source="synthetic",
                )
            )
        else:
            samples.append(ReceiptSample(image=path, ticket=ticket, source="synthetic"))
    return samples


def build_samples(config: dict[str, Any]) -> tuple[list[ReceiptSample], list[ReceiptSample]]:
    """Assemble les listes train/val depuis les sources configurees."""
    data_cfg = config["data"]
    sources = config["sources"]
    train: list[ReceiptSample] = []
    val: list[ReceiptSample] = []

    diverse = bool(data_cfg.get("synthetic_diverse", False))
    distort = bool(data_cfg.get("synthetic_distort", False))
    distort_intensity = str(data_cfg.get("synthetic_distort_intensity", "medium"))

    if "synthetic" in sources:
        if data_cfg.get("synthetic_on_the_fly"):
            count = int(data_cfg.get("synthetic_count", 2000))
            base_seed = int(data_cfg.get("synthetic_seed", 0))
            samples = build_live_synthetic_samples(
                count,
                seed=base_seed,
                diverse=diverse or True,
                distort=distort,
                distort_intensity=distort_intensity,
            )
        else:
            samples = load_disk_synthetic_samples(
                data_cfg["synthetic_dir"],
                diverse=diverse,
                distort=distort,
                distort_intensity=distort_intensity,
            )
            extra_dir = data_cfg.get("synthetic_extra_dir")
            if extra_dir:
                samples.extend(
                    load_disk_synthetic_samples(
                        extra_dir,
                        diverse=diverse or True,
                        distort=distort or True,
                        distort_intensity=distort_intensity,
                    )
                )
            if not samples:
                raise FileNotFoundError(
                    f"No synthetic data in {data_cfg['synthetic_dir']!r} — "
                    "run scripts/generate_synthetic.py or set synthetic_on_the_fly: true."
                )

        random.Random(0).shuffle(samples)
        limit = data_cfg.get("synthetic_limit")
        if limit:
            samples = samples[: int(limit)]
        n_val = max(1, int(len(samples) * data_cfg.get("synthetic_val_fraction", 0.05)))
        val.extend(samples[:n_val])
        train.extend(samples[n_val:])

    if "cord" in sources:
        from receipt_vlm.data.cord_adapter import load_cord_samples

        limit = data_cfg.get("cord_limit")
        train.extend(load_cord_samples("train", limit=limit))
        val.extend(load_cord_samples("validation", limit=64))

    if "sroie" in sources and data_cfg.get("sroie_dir"):
        from receipt_vlm.data.sroie_adapter import load_sroie_samples

        sroie = load_sroie_samples(data_cfg["sroie_dir"])
        cut = max(1, len(sroie) // 10)
        val.extend(sroie[:cut])
        train.extend(sroie[cut:])

    if "real" in sources:
        from receipt_vlm.data.real_photos import load_real_samples

        train.extend(
            load_real_samples(
                data_cfg["real_images_dir"],
                data_cfg["real_labels_dir"],
                split="train",
            )
        )
        val.extend(
            load_real_samples(
                data_cfg["real_images_dir"],
                data_cfg["real_labels_dir"],
                split="val",
            )
        )

    if not train:
        raise ValueError(f"No training samples for sources {sources!r}")
    return train, val
