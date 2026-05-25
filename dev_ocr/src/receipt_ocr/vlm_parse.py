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


_TICKET_MARKER = re.compile(r'\{\s*"ticket"\s*:', re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def extract_json_candidate(text: str) -> str:
    """Return the best JSON substring chosen by :func:`_loads_json`."""
    payload = _loads_json(text)
    if payload is None:
        return strip_markdown_json_fence(text.strip())
    return json.dumps(payload, ensure_ascii=False)


def loads_vlm_payload(text: str) -> dict | None:
    """Parse JSON object from VLM output without full schema normalization."""
    return _loads_json(text)


def _collect_json_candidates(text: str) -> list[str]:
    """Build parse attempts from noisy VLM text (single blob or repeated JSON)."""
    stripped = strip_markdown_json_fence(text.strip())
    if not stripped:
        return []

    candidates: list[str] = [stripped]

    for match in _TICKET_MARKER.finditer(stripped):
        if match.start() > 0:
            candidates.append(stripped[match.start() :])

    parts = re.split(r"\}\s*\n\s*\{", stripped)
    if len(parts) > 1:
        for index, part in enumerate(parts):
            chunk = part.strip()
            if not chunk.startswith("{"):
                chunk = "{" + chunk
            if not chunk.endswith("}"):
                chunk = chunk + "}"
            candidates.append(chunk)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _try_parse_json_string(candidate: str) -> dict | None:
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json  # type: ignore[import-not-found]

            repaired = repair_json(candidate)
            payload = json.loads(repaired)
        except Exception:
            return None
    return payload if isinstance(payload, dict) else None


def _score_vlm_payload(payload: dict[str, Any]) -> int:
    """Prefer payloads with more real products and header fields."""
    ticket = payload.get(TicketField.TICKET.value)
    if not isinstance(ticket, dict):
        if TicketField.PRODUITS.value in payload:
            ticket = payload
        else:
            return 0

    score = 0
    if _as_str(ticket.get(TicketField.CHAINE.value, "")):
        score += 5
    if _as_str(ticket.get(TicketField.DATE.value, "")):
        score += 3
    if _as_str(ticket.get(TicketField.ADRESSE.value, "")):
        score += 1

    products = ticket.get(TicketField.PRODUITS.value)
    if isinstance(products, list):
        for item in products:
            if not isinstance(item, dict):
                continue
            name = _as_str(item.get(ProductField.NOM.value, ""))
            if name:
                score += 10
    return score


def _loads_json(text: str) -> dict | None:
    best: dict[str, Any] | None = None
    best_score = -1
    for candidate in _collect_json_candidates(text):
        payload = _try_parse_json_string(candidate)
        if payload is None:
            continue
        score = _score_vlm_payload(payload)
        if score > best_score:
            best_score = score
            best = payload
    return best


def merge_partial_tickets(parts: list[dict[str, Any]]) -> dict:
    """Merge header/date/products partial dicts into a full ticket payload."""
    merged: dict[str, Any] = {
        TicketField.DATE.value: "",
        TicketField.CHAINE.value: "",
        TicketField.ADRESSE.value: "",
        TicketField.PRODUITS.value: [],
    }
    for part in parts:
        if not isinstance(part, dict):
            continue
        if TicketField.TICKET.value in part and isinstance(part[TicketField.TICKET.value], dict):
            part = part[TicketField.TICKET.value]
        for key in (TicketField.DATE.value, TicketField.CHAINE.value, TicketField.ADRESSE.value):
            value = part.get(key)
            if isinstance(value, str) and value.strip() and not merged[key]:
                merged[key] = value.strip()
        products = part.get(TicketField.PRODUITS.value)
        if isinstance(products, list) and products:
            merged[TicketField.PRODUITS.value] = products
    return {TicketField.TICKET.value: merged}


def try_parse_vlm_json(text: str) -> dict | None:
    """Return a normalized receipt dict if ``text`` is VLM JSON, else ``None``."""
    payload = _loads_json(text)
    if payload is None:
        return None
    if TicketField.TICKET.value not in payload:
        if any(k in payload for k in (TicketField.DATE.value, TicketField.CHAINE.value, TicketField.PRODUITS.value)):
            payload = merge_partial_tickets([payload])
        else:
            return None
    try:
        return normalize_vlm_ticket(payload)
    except ReceiptParseError:
        return None


def normalize_vlm_ticket(payload: dict[str, Any]) -> dict:
    """Validate and coerce a VLM ``{"ticket": ...}`` payload to the package schema."""
    ticket_raw = payload.get(TicketField.TICKET.value)
    if not isinstance(ticket_raw, dict):
        raise ReceiptParseError("VLM JSON: 'ticket' must be an object.")

    date = _coerce_vlm_date(_as_str(ticket_raw.get(TicketField.DATE.value, "")))
    if date and not _looks_like_output_date(date):
        raise ReceiptParseError(
            f"VLM JSON: invalid date {date!r} (expected {OUTPUT_DATE_FORMAT!r})."
        )

    chain = _as_str(ticket_raw.get(TicketField.CHAINE.value, ""))
    if chain and not _looks_like_store_name(chain):
        raise ReceiptParseError(f"VLM JSON: invalid chaine_supermarche {chain!r}.")
    address = _as_str(ticket_raw.get(TicketField.ADRESSE.value, ""))
    products_raw = ticket_raw.get(TicketField.PRODUITS.value, [])
    if products_raw is None:
        products_raw = []
    if not isinstance(products_raw, list):
        raise ReceiptParseError("VLM JSON: 'produits' must be a list.")

    products: list[dict[str, Any]] = []
    for index, item in enumerate(products_raw):
        if not isinstance(item, dict):
            continue
        name = _normalize_product_name(_as_str(item.get(ProductField.NOM.value, "")))
        if not name:
            continue
        price = _round_price(_as_price(item.get(ProductField.PRIX.value)))
        units = _as_units(item.get(ProductField.UNITES.value))
        products.append(
            {
                ProductField.NOM.value: name,
                ProductField.PRIX.value: price,
                ProductField.UNITES.value: units,
            }
        )

    products = _dedupe_vlm_products(products)

    return {
        TicketField.TICKET.value: {
            TicketField.DATE.value: date,
            TicketField.CHAINE.value: chain,
            TicketField.ADRESSE.value: address,
            TicketField.PRODUITS.value: products,
        }
    }


def _normalize_product_name(name: str) -> str:
    """Collapse whitespace for stable duplicate detection."""
    return _WHITESPACE.sub(" ", name.strip())


def _round_price(value: float) -> float:
    return round(value, 2)


def _product_dedup_key(product: dict[str, Any]) -> tuple[str, float, int]:
    return (
        product[ProductField.NOM.value],
        product[ProductField.PRIX.value],
        product[ProductField.UNITES.value],
    )


def _dedupe_vlm_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove exact duplicate line items (common VLM hallucination)."""
    seen: set[tuple[str, float, int]] = set()
    deduped: list[dict[str, Any]] = []
    for product in products:
        key = _product_dedup_key(product)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(product)
    return deduped


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
    if isinstance(value, float):
        if value <= 0:
            return 1
        return max(1, int(round(value)))
    if isinstance(value, str) and value.strip().isdigit():
        return max(1, int(value.strip()))
    raise ReceiptParseError(f"VLM JSON: invalid unites value {value!r}.")


_VLM_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^(\d{2})[/\-.](\d{2})[/\-.](\d{4})\s+(\d{1,2})[:hH](\d{2})$"),
        "{2}{1}{0} {3:0>2}:{4}",
    ),
    (
        re.compile(r"^(\d{2})[/\-.](\d{2})[/\-.](\d{2})\s+(\d{1,2})[:hH](\d{2})$"),
        "20{2}{1}{0} {3:0>2}:{4}",
    ),
    (
        re.compile(r"^(\d{4})[/\-.](\d{2})[/\-.](\d{2})\s+(\d{1,2})[:hH](\d{2})$"),
        "{0}{1}{2} {3:0>2}:{4}",
    ),
    (
        re.compile(r"^(\d{2})[/\-.](\d{2})[/\-.](\d{4})$"),
        "{2}{1}{0} 00:00",
    ),
    (
        re.compile(r"^(\d{2})[/\-.](\d{2})[/\-.](\d{2})$"),
        "20{2}{1}{0} 00:00",
    ),
)


def _coerce_vlm_date(value: str) -> str:
    """Normalize common receipt date strings to ``yyyyMMdd HH:mm``."""
    stripped = value.strip()
    if not stripped or _looks_like_output_date(stripped):
        return stripped
    for pattern, template in _VLM_DATE_PATTERNS:
        match = pattern.match(stripped)
        if match:
            try:
                return template.format(*match.groups())
            except (ValueError, IndexError):
                continue
    return stripped


def _looks_like_output_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{8}\s+\d{2}:\d{2}", value.strip()))


def _looks_like_store_name(value: str) -> bool:
    from receipt_ocr.vlm_validate import looks_like_store_name

    return looks_like_store_name(value)
