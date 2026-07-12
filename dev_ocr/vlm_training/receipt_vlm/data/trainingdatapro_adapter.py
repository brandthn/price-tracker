"""TrainingDataPro "OCR Receipts Text Detection" adapter — real English receipts.

HF dataset ``TrainingDataPro/ocr-receipts-text-detection``: 20 US grocery/retail
receipts with CVAT-XML box annotations carrying a ``text`` attribute per box
(labels: ``shop``, ``item``, ``date_time``, ``total``). Unlike CORD/SROIE this
gives real transcribed text directly — no pseudo-labelling needed.

Expected local layout (after extracting the HF ``data/images.tar.gz`` next to
``data/annotations.xml``, see ``scripts/fetch_validation_data.py::fetch_trainingdatapro``)::

    trainingdatapro_dir/
        annotations.xml
        0.jpg
        1.jpg
        ...

Licence: CC-BY-NC-ND-4.0 (non-commercial, no derivatives) — stricter than the
other sources here; keep to non-commercial academic evaluation use.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from receipt_vlm.data.dataset import ReceiptSample
from receipt_vlm.data.schema import DATE_FORMAT, Product, Ticket

_PRICE = re.compile(r"\d+\.\d{2}")
_DATE_PATTERNS = ("%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%y", "%m/%d/%Y")


def _last_price(text: str) -> Optional[float]:
    """The item's price is the LAST 2-decimal number in the OCR line.

    POS export lines like "BANANAS 000000004011KF 0.41 lb @ 1 lb /0.49 0.20 N"
    mix a PLU/barcode, a weight, and a unit price before the final extended
    price (``0.20``) — barcodes have no decimal point, so the last decimal
    match is reliably the line total.
    """
    matches = _PRICE.findall(text or "")
    if not matches:
        return None
    try:
        return round(float(matches[-1]), 2)
    except ValueError:
        return None


def _item_name(text: str) -> str:
    """Leading run of alphabetic tokens, stopping at the first digit-bearing
    token (PLU/barcode/price) — e.g. "FRAP 001200010451 F 5.48 N" -> "FRAP".
    """
    words: list[str] = []
    for token in (text or "").split():
        if any(ch.isdigit() for ch in token):
            break
        words.append(token)
    return " ".join(words).strip()


def _parse_date(text: str) -> str:
    from datetime import datetime

    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    for pattern in _DATE_PATTERNS:
        try:
            moment = datetime.strptime(cleaned, pattern)
        except ValueError:
            continue
        return moment.strftime(DATE_FORMAT)
    return ""


def ticket_from_trainingdatapro_image(image_el: ET.Element) -> Ticket:
    """Map one CVAT ``<image>`` element's boxes to a canonical :class:`Ticket`."""
    shop = ""
    date_time = ""
    produits: list[Product] = []

    for box in image_el.findall("box"):
        label = box.get("label", "")
        attr = box.find("attribute[@name='text']")
        text = (attr.text or "").strip() if attr is not None else ""
        if not text:
            continue
        if label == "shop" and not shop:
            shop = text[:80]
        elif label == "date_time" and not date_time:
            date_time = text
        elif label == "item":
            name = _item_name(text)
            price = _last_price(text)
            if not name or price is None:
                continue
            produits.append(Product(name[:80], price, 1))
        # "total" is not part of the canonical Ticket schema — ignored.

    return Ticket(
        date=_parse_date(date_time),
        chaine_supermarche=shop,
        adresse="",
        produits=produits,
    )


def load_trainingdatapro_samples(
    dataset_dir: str | Path, limit: Optional[int] = None
) -> list[ReceiptSample]:
    """Load TrainingDataPro receipts (images + ``annotations.xml``) as ReceiptSamples."""
    directory = Path(dataset_dir)
    tree = ET.parse(directory / "annotations.xml")
    samples: list[ReceiptSample] = []
    for image_el in tree.getroot().findall("image"):
        name = image_el.get("name", "")
        fname = Path(name).name if name else ""
        image_path = directory / fname
        if not fname or not image_path.is_file():
            # Case-insensitive extension fallback (e.g. "6.JPG" on disk).
            candidates = list(directory.glob(f"{Path(fname).stem}.*")) if fname else []
            if not candidates:
                continue
            image_path = candidates[0]
        ticket = ticket_from_trainingdatapro_image(image_el)
        if not ticket.produits:
            continue
        samples.append(ReceiptSample(image=image_path, ticket=ticket, source="trainingdatapro"))
        if limit is not None and len(samples) >= limit:
            break
    return samples
