"""Map le dict Gemini → row shapes Cloud SQL (`tickets` / `prix_extraits`).

Schéma produit attendu : ``nom_produit``, ``quantite``, ``prix_unitaire``,
``montant_ttc`` (total payé de la ligne). Produit la même forme de sortie DB que
le worker tier-1 (``quantity`` / ``unit_price`` / ``line_total``).
"""

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


def _line_total(item: dict) -> Decimal:
    """Montant payé de la ligne : ``montant_ttc`` si présent, sinon PU × quantité."""
    montant = item.get("montant_ttc")
    if montant is not None:
        return Decimal(str(montant))
    unit = Decimal(str(item.get("prix_unitaire") or 0))
    qty = Decimal(str(item.get("quantite") or 1))
    return unit * qty


def map_ticket_fields(
    ocr_result: dict,
    engine: str,
    duration_ms: int,
    confidence: float,
) -> dict[str, Any]:
    """Colonnes pour ``UPDATE tickets`` au succès OCR.

    Total = somme des montants payés des lignes (source de vérité du ticket).
    """
    ticket = ocr_result.get("ticket") or {}
    produits = ticket.get("produits") or []

    line_totals = [
        _line_total(item) for item in produits if isinstance(item, dict)
    ]
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
    """Une row dict par produit pour l'upsert ``prix_extraits``."""
    ticket = ocr_result.get("ticket") or {}
    produits = ticket.get("produits") or []
    rows: list[dict[str, Any]] = []

    for line_index, item in enumerate(produits):
        if not isinstance(item, dict):
            continue
        raw_text = (item.get("nom_produit") or "").strip()
        if not raw_text:
            continue

        quantity = float(item.get("quantite") or 1) or 1.0
        line_total = round(float(_line_total(item)), 2)
        unit_price = float(item.get("prix_unitaire") or 0)
        # Prix unitaire absent mais montant + quantité connus → on le dérive.
        if unit_price == 0 and quantity:
            unit_price = round(line_total / quantity, 2)

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
