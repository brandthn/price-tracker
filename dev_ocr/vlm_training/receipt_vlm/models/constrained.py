"""JSON-constrained decoding — from-scratch token-mask state machine.

Replaces the draft spec's undefined "JSON schema head": a trained head cannot
*guarantee* valid JSON, whereas this acceptor does, deterministically, with
zero trainable parameters.

A character-level state machine encodes the grammar of the canonical schema:

    {"ticket":{"date":STR,"chaine_supermarche":STR,"adresse":STR,
               "produits":[ {"nom_produit":STR,"prix_unitaire_ou_kg":PRICE,
                             "unites":INT} (,{...})* ]}}

``STR`` is a quoted JSON string (escapes supported), ``PRICE`` is
``digits.dd`` (exactly two decimals, matching the deterministic serializer in
:mod:`receipt_vlm.data.schema`) and ``INT`` is a positive integer.

At each generation step the decoder probes candidate tokens in descending
logit order and accepts the first whose decoded text keeps the machine in a
valid state — a lazy token mask.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence


_LIT_HEAD = '{"ticket":{"date":'
_LIT_CHAINE = ',"chaine_supermarche":'
_LIT_ADRESSE = ',"adresse":'
_LIT_PRODUITS = ',"produits":['
_LIT_NOM = '{"nom_produit":'
_LIT_PRIX = ',"prix_unitaire_ou_kg":'
_LIT_UNITES = ',"unites":'
_LIT_TAIL = "]}}"

_TOP_LITERALS = (_LIT_HEAD, _LIT_CHAINE, _LIT_ADRESSE)  # each followed by STR
_PRODUCT_LITERALS = (_LIT_NOM, _LIT_PRIX, _LIT_UNITES)

_ESCAPABLE = set('"\\/bfnrt')
_HEX = set("0123456789abcdefABCDEF")

MAX_STRING_CHARS = 120
MAX_PRICE_INT_DIGITS = 5
MAX_UNITS_DIGITS = 4
MAX_PRODUCTS = 80

_MINIMAL_PRODUCT = '{"nom_produit":"?","prix_unitaire_ou_kg":0.00,"unites":1}'


@dataclass(frozen=True)
class _State:
    """Snapshot of the acceptor (cheap to copy for non-mutating probes).

    ``mode`` is one of:
        lit        — matching the current fixed literal
        str_open   — expecting the opening quote of a string value
        str        — inside a string value
        esc        — after a backslash inside a string
        esc_hex    — inside a ``\\uXXXX`` escape
        price_int  — integer part of a price
        price_frac — decimal part of a price (exactly 2 digits)
        int        — ``unites`` value (closed by ``}``)
        prod_open  — expecting ``{`` (first product) or ``]`` (empty list)
        prod_next  — expecting ``{`` (product after a comma)
        prod_sep   — after a product: expecting ``,`` or ``]``
        done       — full document accepted
    """

    segment: int = 0
    literal_pos: int = 0
    mode: str = "lit"
    str_len: int = 0
    esc_hex_left: int = 0
    num_digits: int = 0
    frac_digits: int = 0
    n_products: int = 0
    in_product: bool = False
    product_field: int = 0


def _current_literal(state: _State) -> str:
    if state.in_product:
        return _PRODUCT_LITERALS[state.product_field]
    if state.segment < len(_TOP_LITERALS):
        return _TOP_LITERALS[state.segment]
    if state.segment == len(_TOP_LITERALS):
        return _LIT_PRODUITS
    return _LIT_TAIL


def _after_literal(state: _State) -> _State:
    """The current literal is fully consumed → enter the following value."""
    state = replace(state, literal_pos=0)
    if state.in_product:
        if state.product_field == 0:
            return replace(state, mode="str_open")
        if state.product_field == 1:
            return replace(state, mode="price_int", num_digits=0)
        return replace(state, mode="int", num_digits=0)
    if state.segment < len(_TOP_LITERALS):
        return replace(state, mode="str_open")
    if state.segment == len(_TOP_LITERALS):
        return replace(state, mode="prod_open")
    return replace(state, mode="done")


def _after_value(state: _State) -> _State:
    """A STR or PRICE value finished → advance to the next literal."""
    if state.in_product:
        return replace(state, mode="lit", literal_pos=0,
                       product_field=state.product_field + 1,
                       str_len=0, num_digits=0, frac_digits=0)
    return replace(state, mode="lit", literal_pos=0,
                   segment=state.segment + 1, str_len=0)


def _enter_tail(state: _State) -> _State:
    """``]`` consumed → match the remaining ``}}`` of the tail literal."""
    return replace(state, mode="lit", segment=len(_TOP_LITERALS) + 1,
                   literal_pos=1, in_product=False, product_field=0)


def _enter_product(state: _State) -> _State:
    """``{`` consumed → match ``_LIT_NOM`` from its second character."""
    return replace(state, mode="lit", literal_pos=1,
                   in_product=True, product_field=0)


def _step(state: _State, char: str) -> Optional[_State]:
    """Return the successor state for ``char``, or None if invalid."""
    mode = state.mode

    if mode == "done":
        return None

    if mode == "lit":
        literal = _current_literal(state)
        if char != literal[state.literal_pos]:
            return None
        state = replace(state, literal_pos=state.literal_pos + 1)
        if state.literal_pos == len(literal):
            return _after_literal(state)
        return state

    if mode == "str_open":
        if char != '"':
            return None
        return replace(state, mode="str", str_len=0)

    if mode == "str":
        if char == '"':
            return _after_value(state)
        if char == "\\":
            return replace(state, mode="esc")
        if ord(char) < 0x20 or state.str_len >= MAX_STRING_CHARS:
            return None
        return replace(state, str_len=state.str_len + 1)

    if mode == "esc":
        if char == "u":
            return replace(state, mode="esc_hex", esc_hex_left=4)
        if char in _ESCAPABLE:
            return replace(state, mode="str", str_len=state.str_len + 1)
        return None

    if mode == "esc_hex":
        if char not in _HEX:
            return None
        left = state.esc_hex_left - 1
        if left == 0:
            return replace(state, mode="str", esc_hex_left=0,
                           str_len=state.str_len + 1)
        return replace(state, esc_hex_left=left)

    if mode == "price_int":
        if char.isdigit():
            if state.num_digits >= MAX_PRICE_INT_DIGITS:
                return None
            return replace(state, num_digits=state.num_digits + 1)
        if char == "." and state.num_digits > 0:
            return replace(state, mode="price_frac", frac_digits=0)
        return None

    if mode == "price_frac":
        if not char.isdigit() or state.frac_digits >= 2:
            return None
        frac = state.frac_digits + 1
        if frac == 2:
            return _after_value(replace(state, frac_digits=0, num_digits=0))
        return replace(state, frac_digits=frac)

    if mode == "int":
        if char.isdigit():
            if state.num_digits == 0 and char == "0":
                return None  # unites >= 1
            if state.num_digits >= MAX_UNITS_DIGITS:
                return None
            return replace(state, num_digits=state.num_digits + 1)
        if char == "}" and state.num_digits > 0:
            return replace(state, mode="prod_sep", num_digits=0,
                           in_product=False, product_field=0,
                           n_products=state.n_products + 1)
        return None

    if mode == "prod_open":
        if char == "{" and state.n_products < MAX_PRODUCTS:
            return _enter_product(state)
        if char == "]":
            return _enter_tail(state)
        return None

    if mode == "prod_next":
        if char == "{" and state.n_products < MAX_PRODUCTS:
            return _enter_product(state)
        return None

    if mode == "prod_sep":
        if char == ",":
            if state.n_products >= MAX_PRODUCTS:
                return None
            return replace(state, mode="prod_next")
        if char == "]":
            return _enter_tail(state)
        return None

    return None


class CanonicalJsonStateMachine:
    """Character-level acceptor for the canonical receipt JSON grammar."""

    def __init__(self) -> None:
        self._state = _State()

    def is_complete(self) -> bool:
        return self._state.mode == "done"

    def feed_text(self, text: str) -> bool:
        """Consume ``text`` entirely; state is unchanged when invalid."""
        candidate = self._state
        for char in text:
            next_state = _step(candidate, char)
            if next_state is None:
                return False
            candidate = next_state
        self._state = candidate
        return True

    def try_feed_text(self, text: str) -> bool:
        """Check ``text`` without mutating the machine."""
        candidate = self._state
        for char in text:
            next_state = _step(candidate, char)
            if next_state is None:
                return False
            candidate = next_state
        return True

    def forced_continuation(self) -> str:
        """A minimal valid continuation for the current state.

        Fallback when no vocabulary token fits (degenerate logits): the
        decoder re-encodes this text and continues. Repeatedly applying it
        always terminates in the ``done`` state.
        """
        state = self._state
        mode = state.mode
        if mode == "done":
            return ""
        if mode == "lit":
            return _current_literal(state)[state.literal_pos:]
        if mode == "str_open":
            return '""'
        if mode == "str":
            return '"'
        if mode == "esc":
            return "n"
        if mode == "esc_hex":
            return "0" * state.esc_hex_left
        if mode == "price_int":
            return "0.00" if state.num_digits == 0 else ".00"
        if mode == "price_frac":
            return "0" * (2 - state.frac_digits)
        if mode == "int":
            return "1}" if state.num_digits == 0 else "}"
        if mode in ("prod_open", "prod_sep"):
            return "]"
        if mode == "prod_next":
            return _MINIMAL_PRODUCT
        raise RuntimeError(f"unexpected state {mode!r}")


def pick_token(
    logits_row,
    machine: CanonicalJsonStateMachine,
    token_texts: Sequence[str],
    top_k: int = 64,
    max_scan: int = 4096,
) -> tuple[Optional[int], str]:
    """Pick the highest-logit token whose text keeps the grammar valid.

    Args:
        logits_row: 1D tensor of next-token logits.
        machine: grammar state — mutated when a token is accepted.
        token_texts: precomputed decoded text per vocabulary id.
        top_k: fast path — probe only the top-k tokens first.
        max_scan: cap on the slow-path scan over the sorted vocabulary.

    Returns:
        ``(token_id, accepted_text)``; ``token_id`` is None when no single
        token fits and the caller must force ``accepted_text`` by re-encoding
        it (the machine has already consumed it in that case).
    """
    import torch

    k = min(top_k, logits_row.shape[-1])
    candidates = torch.topk(logits_row, k).indices.tolist()
    seen = set(candidates)
    for idx in candidates:
        text = token_texts[idx]
        if text and "\ufffd" not in text and machine.feed_text(text):
            return idx, text

    order = torch.argsort(logits_row, descending=True)[:max_scan].tolist()
    for idx in order:
        if idx in seen:
            continue
        text = token_texts[idx]
        if text and "\ufffd" not in text and machine.feed_text(text):
            return idx, text

    forced = machine.forced_continuation()
    if forced and machine.feed_text(forced):
        return None, forced
    raise RuntimeError("Constrained decoder is stuck: no valid continuation.")
