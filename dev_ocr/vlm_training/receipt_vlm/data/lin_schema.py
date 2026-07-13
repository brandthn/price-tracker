"""Schema linearise : la cible compacte que le decodeur OCR-VLM produit.

Le decodeur sort une sequence plate avec des marqueurs de champ. Ce module fait la
conversion dans les deux sens avec le Ticket canonique.

    [STORE] Carrefour [DATE] 20260101 12:00 [ADDR] 12 rue ... [ITEM] LAIT 1L [PRICE] 1.09
        [ITEM] OEUFS X6 [QTY] 2 [PRICE] 3.98 [END]

Dans un item, [PRICE] ferme la ligne, donc la quantite (omise quand elle vaut 1) doit
venir avant. Les champs d'en-tete vides sont omis.

linear_to_ticket est volontairement tolerant : la sortie du modele est rarement
parfaite, et on prefere recuperer ce qui est recuperable plutot que tout jeter.
"""

from __future__ import annotations

import re

from receipt_vlm.data.schema import Product, Ticket

# Les marqueurs de champ. Ce sont des tokens uniques cote tokenizer.
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
    """Enleve les marqueurs de champ et les espaces autour d'une valeur."""
    return _MARKER_RE.sub(" ", str(value or "")).strip()


def ticket_to_linear(ticket: Ticket) -> str:
    """Serialise un Ticket vers la sequence linearisee."""
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
    """Reconstruit un Ticket depuis une sequence linearisee, meme imparfaite.

    Tolere les marqueurs manquants ou dupliques, la bouillie en fin de sequence, et un
    ``[PRICE]`` (or a new ``[ITEM]``/``[END]``) closes the current product; items without a
    price are dropped. Never raises — returns whatever could be recovered.
    """
    # Decoupe en paires (marqueur, valeur), en ignorant ce qui precede le 1er marqueur.
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
            _flush(None)  # un nouvel item sans prix pour le precedent : on jette le precedent
            cur_name = value
        elif marker == TOK_PRICE:
            _flush(_parse_price(value))
        elif marker == TOK_QTY:
            cur_qty = _parse_qty(value)
        elif marker == TOK_END:
            break
    _flush(None)

    return Ticket(date=date, chaine_supermarche=store, adresse=addr, produits=produits)
