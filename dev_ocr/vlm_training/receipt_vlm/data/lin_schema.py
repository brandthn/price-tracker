"""Linearized schema — the compact Donut-style target the OCR-VLM decoder emits.

The decoder produces a flat token sequence with field markers; this module converts a
canonical :class:`Ticket` to/from that sequence. ``linear_to_ticket`` is deliberately
*forgiving* (best-effort recovery from partial/imperfect model output) — that's the
"algorithmically treat the output to build the final JSON" step. Round-trips exactly for
well-formed input (see the unit test at the bottom / ``tests``).

Sequence shape (markers are atomic special tokens, values are raw text)::

    [STORE] Carrefour [DATE] 20260101 12:00 [ADDR] 12 rue ... [ITEM] LAIT 1L [PRICE] 1.09
        [ITEM] EGGS X6 [QTY] 2 [PRICE] 3.98 [END]

Per item the order is ``[ITEM] name ([QTY] q)? [PRICE] p`` — ``[PRICE]`` closes the item, so
quantity (omitted when 1) must precede it. Empty header fields are omitted.
"""

from __future__ import annotations

import re

from receipt_vlm.data.schema import Product, Ticket

# Atomic field-marker tokens (also registered as specials in the tokenizer).
TOK_STORE = "[STORE]"
TOK_DATE = "[DATE]"
TOK_ADDR = "[ADDR]"
TOK_ITEM = "[ITEM]"
TOK_PRICE = "[PRICE]"
TOK_QTY = "[QTY]"
TOK_END = "[END]"

FIELD_TOKENS: tuple[str, ...] = (TOK_STORE, TOK_DATE, TOK_ADDR, TOK_ITEM, TOK_PRICE, TOK_QTY, TOK_END)

_MARKER_RE = re.compile("|".join(re.escape(t) for t in FIELD_TOKENS))


def _clean(value: str) -> str:
    """Strip any literal marker substrings + surrounding whitespace from a value."""
    return _MARKER_RE.sub(" ", str(value or "")).strip()


def ticket_to_linear(ticket: Ticket) -> str:
    """Serialize a :class:`Ticket` to the linearized target string."""
    parts: list[str] = []
    store = _clean(ticket.chaine_supermarche)
    if store:
        parts.append(f"{TOK_STORE} {store}")
    date = _clean(ticket.date)
    if date:
        parts.append(f"{TOK_DATE} {date}")
    addr = _clean(ticket.adresse)
    if addr:
        parts.append(f"{TOK_ADDR} {addr}")
    for product in ticket.produits:
        name = _clean(product.nom_produit)
        if not name:
            continue
        parts.append(f"{TOK_ITEM} {name}")
        if int(product.unites) != 1:
            parts.append(f"{TOK_QTY} {int(product.unites)}")
        parts.append(f"{TOK_PRICE} {float(product.prix_unitaire_ou_kg):.2f}")
    parts.append(TOK_END)
    return " ".join(parts)


def _parse_price(text: str) -> float:
    match = re.search(r"-?\d+(?:[.,]\d+)?", text or "")
    if not match:
        return 0.0
    try:
        return round(float(match.group(0).replace(",", ".")), 2)
    except ValueError:
        return 0.0


def _parse_qty(text: str) -> int:
    match = re.search(r"\d+", text or "")
    return max(1, int(match.group(0))) if match else 1


def linear_to_ticket(text: str) -> Ticket:
    """Best-effort parse of a (possibly imperfect) linearized string into a Ticket.

    Tolerates missing/duplicated markers, trailing junk, and a missing ``[END]``. A
    ``[PRICE]`` (or a new ``[ITEM]``/``[END]``) closes the current product; items without a
    price are dropped. Never raises — returns whatever could be recovered.
    """
    # Split into (marker, value) chunks, ignoring text before the first marker.
    chunks: list[tuple[str, str]] = []
    pos = 0
    for m in _MARKER_RE.finditer(text or ""):
        if chunks:
            chunks[-1] = (chunks[-1][0], text[pos:m.start()].strip())
        chunks.append((m.group(0), ""))
        pos = m.end()
    if chunks:
        chunks[-1] = (chunks[-1][0], (text or "")[pos:].strip())

    date = store = addr = ""
    produits: list[Product] = []
    cur_name: str | None = None
    cur_qty = 1

    def _flush(price: float | None) -> None:
        nonlocal cur_name, cur_qty
        if cur_name and price is not None:
            produits.append(Product(cur_name[:80], price, cur_qty))
        cur_name, cur_qty = None, 1

    for marker, value in chunks:
        if marker == TOK_STORE:
            store = value[:80]
        elif marker == TOK_DATE:
            date = value[:40]
        elif marker == TOK_ADDR:
            addr = value[:120]
        elif marker == TOK_ITEM:
            _flush(None)  # a new item without a price for the previous one -> drop previous
            cur_name = value
        elif marker == TOK_PRICE:
            _flush(_parse_price(value))
        elif marker == TOK_QTY:
            cur_qty = _parse_qty(value)
        elif marker == TOK_END:
            break
    _flush(None)

    return Ticket(date=date, chaine_supermarche=store, adresse=addr, produits=produits)
