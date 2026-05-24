"""Parse and validate JSON returned by VLM backends."""

from __future__ import annotations

import json
import re
from typing import Any

from receipt_ocr.constants import OUTPUT_DATE_FORMAT, ProductField, TicketField
from receipt_ocr.exceptions import ReceiptParseError

_JSON_FENCE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_JSON_FENCE_END = re.compile(r"\n?```\s*$")


def strip_markdown_json_fence(text: str) -> str:
    """Remove optional ```json ... ``` wrappers from model output."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = _JSON_FENCE.sub("", stripped, count=1)
    stripped = _JSON_FENCE_END.sub("", stripped)
    return stripped.strip()


def try_parse_vlm_json(text: str) -> dict | None:
    """Return a normalized receipt dict if ``text`` is VLM JSON, else ``None``."""
    candidate = strip_markdown_json_fence(text)
    if not candidate.startswith("{"):
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if TicketField.TICKET.value not in payload:
        return None
    return normalize_vlm_ticket(payload)


def normalize_vlm_ticket(payload: dict[str, Any]) -> dict:
    """Validate and coerce a VLM ``{"ticket": ...}`` payload to the package schema."""
    ticket_raw = payload.get(TicketField.TICKET.value)
    if not isinstance(ticket_raw, dict):
        raise ReceiptParseError("VLM JSON: 'ticket' must be an object.")

    date = _as_str(ticket_raw.get(TicketField.DATE.value, ""))
    if date and not _looks_like_output_date(date):
        raise ReceiptParseError(
            f"VLM JSON: invalid date {date!r} (expected {OUTPUT_DATE_FORMAT!r})."
        )

    chain = _as_str(ticket_raw.get(TicketField.CHAINE.value, ""))
    address = _as_str(ticket_raw.get(TicketField.ADRESSE.value, ""))
    products_raw = ticket_raw.get(TicketField.PRODUITS.value, [])
    if products_raw is None:
        products_raw = []
    if not isinstance(products_raw, list):
        raise ReceiptParseError("VLM JSON: 'produits' must be a list.")

    products: list[dict[str, Any]] = []
    for index, item in enumerate(products_raw):
        if not isinstance(item, dict):
            raise ReceiptParseError(f"VLM JSON: produits[{index}] must be an object.")
        name = _as_str(item.get(ProductField.NOM.value, ""))
        if not name.strip():
            continue
        price = _as_price(item.get(ProductField.PRIX.value))
        units = _as_units(item.get(ProductField.UNITES.value))
        products.append(
            {
                ProductField.NOM.value: name.strip(),
                ProductField.PRIX.value: price,
                ProductField.UNITES.value: units,
            }
        )

    return {
        TicketField.TICKET.value: {
            TicketField.DATE.value: date,
            TicketField.CHAINE.value: chain,
            TicketField.ADRESSE.value: address,
            TicketField.PRODUITS.value: products,
        }
    }


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_price(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        cleaned = re.sub(r"[^\d.]", "", cleaned)
        if not cleaned:
            return 0.0
        return float(cleaned)
    raise ReceiptParseError(f"VLM JSON: invalid price value {value!r}.")


def _as_units(value: Any) -> int:
    if value is None or value == "":
        return 1
    if isinstance(value, bool):
        raise ReceiptParseError("VLM JSON: 'unites' must be an integer.")
    if isinstance(value, int):
        return max(1, value)
    if isinstance(value, float) and value.is_integer():
        return max(1, int(value))
    if isinstance(value, str) and value.strip().isdigit():
        return max(1, int(value.strip()))
    raise ReceiptParseError(f"VLM JSON: invalid unites value {value!r}.")


def _looks_like_output_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{8}\s+\d{2}:\d{2}", value.strip()))
