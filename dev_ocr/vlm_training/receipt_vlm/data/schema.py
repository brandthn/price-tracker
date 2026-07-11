"""Canonical receipt schema — single source of truth shared with ``receipt_ocr``.

The training target is the project's canonical JSON serialized
*deterministically* (fixed key order, ``%.2f`` prices, integer ``unites``,
date ``yyyyMMdd HH:mm``) so token-level cross-entropy is well-defined and the
constrained decoder grammar matches exactly.

Field names are imported from :mod:`receipt_ocr.constants` when available so a
schema rename upstream breaks loudly here instead of silently diverging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:  # receipt_ocr is a sibling install; fall back to literals for isolation.
    from receipt_ocr.constants import OUTPUT_DATE_FORMAT, ProductField, TicketField

    KEY_TICKET = TicketField.TICKET.value
    KEY_DATE = TicketField.DATE.value
    KEY_CHAINE = TicketField.CHAINE.value
    KEY_ADRESSE = TicketField.ADRESSE.value
    KEY_PRODUITS = TicketField.PRODUITS.value
    KEY_NOM = ProductField.NOM.value
    KEY_PRIX = ProductField.PRIX.value
    KEY_UNITES = ProductField.UNITES.value
    DATE_FORMAT = OUTPUT_DATE_FORMAT
except ImportError:  # pragma: no cover - exercised only without receipt_ocr
    KEY_TICKET = "ticket"
    KEY_DATE = "date"
    KEY_CHAINE = "chaine_supermarche"
    KEY_ADRESSE = "adresse"
    KEY_PRODUITS = "produits"
    KEY_NOM = "nom_produit"
    KEY_PRIX = "prix_unitaire_ou_kg"
    KEY_UNITES = "unites"
    DATE_FORMAT = "%Y%m%d %H:%M"


@dataclass
class Product:
    """One purchased article line."""

    nom_produit: str
    prix_unitaire_ou_kg: float
    unites: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            KEY_NOM: self.nom_produit,
            KEY_PRIX: round(float(self.prix_unitaire_ou_kg), 2),
            KEY_UNITES: int(self.unites),
        }


@dataclass
class Ticket:
    """Canonical receipt content."""

    date: str = ""  # "yyyyMMdd HH:mm" or empty
    chaine_supermarche: str = ""
    adresse: str = ""
    produits: list[Product] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            KEY_TICKET: {
                KEY_DATE: self.date,
                KEY_CHAINE: self.chaine_supermarche,
                KEY_ADRESSE: self.adresse,
                KEY_PRODUITS: [p.to_dict() for p in self.produits],
            }
        }


def _escape(value: str) -> str:
    """JSON-escape a string (delegates to ``json.dumps``, keeps accents)."""
    return json.dumps(value, ensure_ascii=False)


def _format_price(value: float) -> str:
    return f"{float(value):.2f}"


def serialize_ticket(ticket: Ticket) -> str:
    """Deterministic, compact canonical serialization.

    Hand-rolled (instead of ``json.dumps``) so that number formatting is fixed
    at exactly two decimals — ``json.dumps(1.1)`` would emit ``1.1`` while the
    grammar and training target require ``1.10``.
    """
    parts: list[str] = [
        '{"%s":{' % KEY_TICKET,
        '"%s":%s,' % (KEY_DATE, _escape(ticket.date)),
        '"%s":%s,' % (KEY_CHAINE, _escape(ticket.chaine_supermarche)),
        '"%s":%s,' % (KEY_ADRESSE, _escape(ticket.adresse)),
        '"%s":[' % KEY_PRODUITS,
    ]
    product_parts: list[str] = []
    for product in ticket.produits:
        product_parts.append(
            '{"%s":%s,"%s":%s,"%s":%d}'
            % (
                KEY_NOM,
                _escape(product.nom_produit),
                KEY_PRIX,
                _format_price(product.prix_unitaire_ou_kg),
                KEY_UNITES,
                int(product.unites),
            )
        )
    parts.append(",".join(product_parts))
    parts.append("]}}")
    return "".join(parts)


def ticket_from_dict(payload: dict[str, Any]) -> Ticket:
    """Build a :class:`Ticket` from a (possibly already canonical) dict.

    Accepts both ``{"ticket": {...}}`` and a bare inner dict. Unknown keys are
    ignored; missing keys default to empty values.
    """
    inner = payload.get(KEY_TICKET, payload) if isinstance(payload, dict) else {}
    if not isinstance(inner, dict):
        inner = {}

    produits: list[Product] = []
    raw_products = inner.get(KEY_PRODUITS) or []
    if isinstance(raw_products, list):
        for entry in raw_products:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get(KEY_NOM, "") or "").strip()
            if not name:
                continue
            try:
                price = round(float(entry.get(KEY_PRIX, 0) or 0), 2)
            except (TypeError, ValueError):
                price = 0.0
            try:
                units = max(1, int(entry.get(KEY_UNITES, 1) or 1))
            except (TypeError, ValueError):
                units = 1
            produits.append(Product(name, price, units))

    return Ticket(
        date=str(inner.get(KEY_DATE, "") or "").strip(),
        chaine_supermarche=str(inner.get(KEY_CHAINE, "") or "").strip(),
        adresse=str(inner.get(KEY_ADRESSE, "") or "").strip(),
        produits=produits,
    )


def ticket_from_json(text: str) -> Ticket:
    """Parse a JSON string into a :class:`Ticket` (raises on invalid JSON)."""
    return ticket_from_dict(json.loads(text))
