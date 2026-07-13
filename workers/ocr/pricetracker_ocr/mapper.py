"""Dict canonique de receipt_ocr -> lignes Cloud SQL."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

def _parse_ticket_date(raw: str) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y%m%d %H:%M").date()
    except ValueError:
        return None


def map_ticket_fields(
    ocr_result: dict,
    engine: str,
    duration_ms: int,
    confidence: float,
) -> dict[str, Any]:
    """Colonnes de l'``UPDATE tickets`` quand l'OCR a réussi.

    On garde les noms côté Python (ticket_date, total_amount) ; c'est pg.py qui
    fait la correspondance avec les vraies colonnes (date_ticket, total_eur).
    """
    ticket = ocr_result.get("ticket") or {}
    produits = ticket.get("produits") or []

    line_totals: list[Decimal] = []
    for item in produits:
        if not isinstance(item, dict):
            continue
        unit = Decimal(str(item.get("prix_unitaire_ou_kg") or 0))
        qty = Decimal(str(item.get("unites") or 1))
        line_totals.append(unit * qty)

    total_amount = sum(line_totals, Decimal("0")) if line_totals else None

    return {
        "enseigne": (ticket.get("chaine_supermarche") or "").strip() or None,
        "ticket_date": _parse_ticket_date(ticket.get("date") or ""),
        "total_amount": float(total_amount) if total_amount is not None else None,
        "ocr_confidence": confidence,
        "ocr_engine": engine,
        "ocr_duration_ms": duration_ms,
    }


def map_prix_extraits_rows(ocr_result: dict, ticket_id: str) -> list[dict[str, Any]]:
    """Une ligne par produit, pour l'upsert dans prix_extraits."""
    ticket = ocr_result.get("ticket") or {}
    produits = ticket.get("produits") or []
    rows: list[dict[str, Any]] = []

    for line_index, item in enumerate(produits):
        if not isinstance(item, dict):
            continue
        raw_text = (item.get("nom_produit") or "").strip()
        if not raw_text:
            continue
        unit_price = float(item.get("prix_unitaire_ou_kg") or 0)
        quantity = float(item.get("unites") or 1)
        line_total = round(unit_price * quantity, 2)

        # ean / match_* partent vides : c'est alias_lookup, après l'OCR,
        # qui les remplit (même étage pour tous les tiers).
        rows.append(
            {
                "ticket_id": ticket_id,
                "line_index": line_index,
                "raw_text": raw_text,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "ean": None,
                "match_method": "none",
                "match_confidence": None,
                "needs_validation": True,
                "validated_by_user": False,
            }
        )

    return rows
