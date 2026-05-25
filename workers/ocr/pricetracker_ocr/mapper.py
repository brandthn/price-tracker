"""Map receipt_ocr canonical dict → Cloud SQL row shapes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Phase 8 — EAN matching not yet implemented: ean/match_* are always unset below.


def _parse_ticket_date(raw: str) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y%m%d %H:%M").date()
    except ValueError:
        return None


def map_ticket_fields(
    ocr_result: dict,
    ticket_id: str,
    gcs_path: str,
    engine: str,
    duration_ms: int,
    confidence: float,
) -> dict[str, Any]:
    """Return columns for ``UPDATE tickets`` on OCR success."""
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

    # TODO: derive real confidence from OCR/VLM when exposed by receipt_ocr
    ocr_confidence = confidence

    return {
        "enseigne": (ticket.get("chaine_supermarche") or "").strip() or None,
        "ticket_date": _parse_ticket_date(ticket.get("date") or ""),
        "total_amount": float(total_amount) if total_amount is not None else None,
        "ocr_confidence": ocr_confidence,
        "ocr_engine": engine,
        "ocr_duration_ms": duration_ms,
    }


def map_prix_extraits_rows(ocr_result: dict, ticket_id: str) -> list[dict[str, Any]]:
    """Return one row dict per product for ``prix_extraits`` upsert."""
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

        # Phase 8 — EAN matching not yet implemented
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
