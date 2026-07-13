"""Adaptateur WildReceipt : de vrais tickets anglais, transcrits et classes.

WildReceipt annote chaque boite de texte avec sa transcription ET sa classe de champ
(Store_name_value, Date_value, Prod_item_value, Prod_price_value...). C'est de la
vraie verite terrain, donc aucun pseudo-labelling : on mappe les classes directement
vers le Ticket canonique, en appariant chaque boite produit avec la boite prix qui se
trouve sur la meme ligne.

Disposition attendue : l'extraction de wildreceipt.tar (class_list.txt, train.txt et
test.txt en JSON ligne a ligne, et les images).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from receipt_vlm.data.dataset import ReceiptSample
from receipt_vlm.data.schema import DATE_FORMAT, Product, Ticket

# Les indices de class_list.txt qu'on exploite. Seulement les classes de valeur :
# les *_key et Others ne nous servent a rien.
STORE_NAME, STORE_ADDR, DATE, TIME = 1, 3, 7, 9
PROD_ITEM, PROD_QTY, PROD_PRICE = 11, 13, 15

_PRICE = re.compile(r"\d+[.,]\d{2}")
_DATE_PATTERNS = (
    "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y",
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y",
    "%d %b %Y", "%d %B %Y", "%b %d %Y", "%b %d, %Y",
)


def _center_y(box: list[float]) -> float:
    ys = box[1::2]
    return sum(ys) / len(ys)


def _height(box: list[float]) -> float:
    ys = box[1::2]
    return max(ys) - min(ys)


def _parse_price(text: str) -> Optional[float]:
    match = _PRICE.search(text or "")
    if not match:
        return None
    try:
        return round(float(match.group(0).replace(",", ".")), 2)
    except ValueError:
        return None


def _parse_datetime(date_text: str, time_text: str) -> str:
    """Date (et heure si elle existe) de WildReceipt vers le format canonique.

    Vide si la date est illisible : mieux vaut rien que du n'importe quoi.
    """
    cleaned = re.sub(r"\s+", " ", (date_text or "").strip())
    moment = None
    for pattern in _DATE_PATTERNS:
        try:
            moment = datetime.strptime(cleaned, pattern)
            break
        except ValueError:
            continue
    if moment is None:
        return ""
    hh, mm = 0, 0
    tmatch = re.search(r"(\d{1,2}):(\d{2})", time_text or "")
    if tmatch:
        hh, mm = int(tmatch.group(1)), int(tmatch.group(2))
    return moment.replace(hour=min(hh, 23), minute=min(mm, 59)).strftime(DATE_FORMAT)


def ticket_from_wildreceipt_record(record: dict) -> Ticket:
    """Convertit une annotation WildReceipt en Ticket canonique."""
    by_label: dict[int, list[dict]] = {}
    for ann in record.get("annotations", []):
        by_label.setdefault(int(ann.get("label", -1)), []).append(ann)

    def _joined(label: int, limit: int) -> str:
        boxes = sorted(
            by_label.get(label, []),
            key=lambda a: (_center_y(a["box"]), a["box"][0]),
        )
        return " ".join((b.get("text") or "").strip() for b in boxes).strip()[:limit]

    store = _joined(STORE_NAME, 80)
    address = _joined(STORE_ADDR, 120)
    date_text = _joined(DATE, 40)
    time_text = _joined(TIME, 20)

    prices = list(by_label.get(PROD_PRICE, []))
    used: set[int] = set()
    produits: list[Product] = []
    for item in sorted(by_label.get(PROD_ITEM, []), key=lambda a: _center_y(a["box"])):
        name = (item.get("text") or "").strip()
        if not name:
            continue
        item_y = _center_y(item["box"])
        tol = max(_height(item["box"]) * 1.5, 15.0)
        best, best_d = None, tol
        for idx, price_box in enumerate(prices):
            if idx in used:
                continue
            dist = abs(_center_y(price_box["box"]) - item_y)
            if dist <= best_d:
                best, best_d = idx, dist
        if best is None:
            continue
        price = _parse_price(prices[best].get("text", ""))
        if price is None:
            continue
        used.add(best)
        produits.append(Product(name[:80], price, 1))

    return Ticket(
        date=_parse_datetime(date_text, time_text),
        chaine_supermarche=store,
        adresse=address,
        produits=produits,
    )


def iter_wildreceipt(dataset_dir: str | Path, split_file: str) -> Iterator[tuple[Path, Ticket]]:
    """Yield ``(image_path, Ticket)`` for each usable receipt in a split file."""
    directory = Path(dataset_dir)
    with (directory / split_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            image_path = directory / record["file_name"]
            if not image_path.is_file():
                continue
            ticket = ticket_from_wildreceipt_record(record)
            if not ticket.produits:  # unusable target
                continue
            yield image_path, ticket


def load_wildreceipt_samples(
    dataset_dir: str | Path, split_file: str = "train.txt", limit: Optional[int] = None
) -> list[ReceiptSample]:
    """Load WildReceipt (one split file) as canonical ReceiptSamples."""
    samples: list[ReceiptSample] = []
    for image_path, ticket in iter_wildreceipt(dataset_dir, split_file):
        samples.append(ReceiptSample(image=image_path, ticket=ticket, source="wildreceipt"))
        if limit is not None and len(samples) >= limit:
            break
    return samples
