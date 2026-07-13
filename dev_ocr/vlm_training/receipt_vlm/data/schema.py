"""Schema canonique du ticket, partage avec receipt_ocr.

La cible d'entrainement est le JSON canonique serialise de facon deterministe (ordre
des cles fixe, prix en %.2f, unites entieres, date en yyyyMMdd HH:mm). Sans ca, la
cross-entropy au niveau token n'a pas de sens, et la grammaire du decodeur contraint
ne colle plus.

Les noms de champs sont importes de receipt_ocr.constants quand c'est possible : si le
schema est renomme en amont, on casse ici plutot que de diverger en silence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:  # receipt_ocr est installe a cote. Sans lui, on retombe sur les litteraux.
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
except ImportError:  # pragma: no cover
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
    """Une ligne de produit achete."""

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
    """Le contenu canonique d'un ticket."""

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
    """Echappe une chaine pour du JSON, en gardant les accents."""
    return json.dumps(value, ensure_ascii=False)


def _format_price(value: float) -> str:
    return f"{float(value):.2f}"


def serialize_ticket(ticket: Ticket) -> str:
    """Serialisation canonique, deterministe et compacte.

    Ecrit a la main plutot qu'avec json.dumps, parce qu'on veut un formatage de nombre
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
    """Construit un Ticket depuis un dict, deja canonique ou pas.

    Accepte aussi bien {"ticket": {...}} que le dict interieur tout nu. Les cles
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
    """Parse du JSON vers un Ticket. Leve si le JSON est invalide."""
    return ticket_from_dict(json.loads(text))
