"""Adaptateur CORD : pour l'alignement vision-langage, rien de plus.

CORD est un jeu de tickets coreens et anglais. Le mapping vers le schema canonique perd
beaucoup (ni enseigne ni adresse dans la plupart des echantillons), et c'est assume :
ce dataset apprend au modele a situer le texte dans une mise en page, pas a extraire un
ticket francais.
"""

from __future__ import annotations

import json
import re
from typing import Iterator, Optional

from receipt_vlm.data.dataset import ReceiptSample
from receipt_vlm.data.schema import Product, Ticket

_NUMERIC = re.compile(r"[-+]?\d[\d.,]*")


def _parse_price(raw) -> Optional[float]:
    """Les prix CORD arrivent en chaine : '2,000', '12.000' (des wons) ou '3.50'."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return round(float(raw), 2)
    match = _NUMERIC.search(str(raw))
    if not match:
        return None
    text = match.group(0)
    # Separateurs de milliers : on jette ceux suivis d'exactement 3 chiffres.
    text = re.sub(r"[,.](?=\d{3}(\D|$))", "", text)
    text = text.replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _parse_count(raw) -> int:
    if raw is None:
        return 1
    match = re.search(r"\d+", str(raw))
    if not match:
        return 1
    return max(1, int(match.group(0)))


def _menu_entries(gt_parse: dict) -> Iterator[dict]:
    menu = gt_parse.get("menu") or []
    if isinstance(menu, dict):
        menu = [menu]
    for entry in menu:
        if isinstance(entry, dict):
            yield entry


def ticket_from_cord_ground_truth(ground_truth: str | dict) -> Ticket:
    """Convertit un ground_truth CORD en Ticket canonique."""
    payload = (
        json.loads(ground_truth) if isinstance(ground_truth, str) else ground_truth
    )
    gt_parse = payload.get("gt_parse", payload) or {}

    produits: list[Product] = []
    for entry in _menu_entries(gt_parse):
        name = entry.get("nm")
        if isinstance(name, list):
            name = " ".join(str(part) for part in name)
        name = str(name or "").strip()
        if not name:
            continue
        price = _parse_price(entry.get("price")) or _parse_price(entry.get("unitprice"))
        if price is None:
            continue
        produits.append(Product(name[:80], price, _parse_count(entry.get("cnt"))))

    return Ticket(produits=produits)  # no reliable store/date/address in CORD


class _CordImageLoader:
    """Acces paresseux et picklable : une image decodee par appel, pas 800 en RAM.

    Avoids holding hundreds of decoded PIL images in RAM and survives
    DataLoader worker pickling on Windows (a lambda would not).
    """

    def __init__(self, dataset, index: int) -> None:
        self._dataset = dataset
        self._index = index

    def __call__(self):
        return self._dataset[self._index]["image"]


def load_cord_samples(split: str = "train", limit: Optional[int] = None) -> list[ReceiptSample]:
    """Charge CORD-v2 depuis HuggingFace et le convertit en ReceiptSample.

    Les ground truths sont mappes tout de suite (l'acces colonne est bon marche,
    undecoded); images load lazily at __getitem__ time. Samples whose mapping
    yields zero products are dropped (useless targets).
    """
    from datasets import load_dataset  # import lourd, uniquement a l'entrainement

    dataset = load_dataset("naver-clova-ix/cord-v2", split=split)
    samples: list[ReceiptSample] = []
    for index, ground_truth in enumerate(dataset["ground_truth"]):
        ticket = ticket_from_cord_ground_truth(ground_truth)
        if not ticket.produits:
            continue
        samples.append(
            ReceiptSample(
                image=_CordImageLoader(dataset, index),
                ticket=ticket,
                source="cord",
            )
        )
        if limit is not None and len(samples) >= limit:
            break
    return samples
