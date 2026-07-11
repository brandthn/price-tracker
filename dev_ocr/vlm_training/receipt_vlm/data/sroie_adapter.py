"""SROIE adapter — phase-1 vision→language alignment only.

SROIE (ICDAR 2019) labels four entities per receipt: ``company``, ``date``,
``address``, ``total``. Products are not annotated, so the canonical mapping
keeps header fields only — again, layout grounding, not French extraction.

Expected local layout (official SROIE task-2 format)::

    sroie_dir/
        X00016469612.jpg
        X00016469612.txt      # {"company": ..., "date": ..., "address": ..., "total": ...}
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from receipt_vlm.data.dataset import ReceiptSample
from receipt_vlm.data.schema import DATE_FORMAT, Ticket

_DATE_PATTERNS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%d %b %Y", "%d %B %Y",
)


def normalize_sroie_date(raw: str) -> str:
    """SROIE date string → canonical ``yyyyMMdd HH:mm`` (time unknown → 00:00).

    Returns an empty string when the date cannot be parsed.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text)
    for pattern in _DATE_PATTERNS:
        try:
            moment = datetime.strptime(cleaned, pattern)
        except ValueError:
            continue
        return moment.strftime(DATE_FORMAT).replace("00:00", "00:00")
    return ""


def ticket_from_sroie_entities(entities: dict) -> Ticket:
    return Ticket(
        date=normalize_sroie_date(str(entities.get("date", "") or "")),
        chaine_supermarche=str(entities.get("company", "") or "").strip()[:80],
        adresse=str(entities.get("address", "") or "").strip()[:120],
        produits=[],
    )


def load_sroie_samples(
    sroie_dir: str | Path, limit: Optional[int] = None
) -> list[ReceiptSample]:
    """Load SROIE pairs (image + entity .txt) from a local directory."""
    directory = Path(sroie_dir)
    samples: list[ReceiptSample] = []
    for image_path in sorted(directory.glob("*.jpg")):
        label_path = image_path.with_suffix(".txt")
        if not label_path.exists():
            continue
        try:
            entities = json.loads(label_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        ticket = ticket_from_sroie_entities(entities)
        if not ticket.chaine_supermarche and not ticket.date:
            continue
        samples.append(ReceiptSample(image=image_path, ticket=ticket, source="sroie"))
        if limit is not None and len(samples) >= limit:
            break
    return samples
