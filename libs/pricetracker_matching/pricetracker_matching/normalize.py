"""Pure text normalisation shared by the alias matcher (both OCR workers).

The SAME function is applied **symmetrically** to the incoming OCR label AND to
the stored alias ``raw_text`` at match time — a normalised form is NEVER
persisted (``product_aliases`` keeps the raw label; cf. migration 0004). This is
deliberately independent from the ``catalogue`` worker normaliser
(``pricetracker_catalogue.llm._normalise``), which is lossy: it drops everything
before the first 3-letter run, which would conflate distinct products
(e.g. ``"500G BEURRE"`` and ``"250G BEURRE"`` collapse to ``"beurre"``).

Two axes, kept separate on purpose:

- :func:`normalize_label` — the authoritative label normaliser. Runs only in
  Python (both sides of every comparison), so it can use full Unicode accent
  folding without any SQL counterpart to keep in sync.
- :func:`enseigne_key` — a *coarse* enseigne fold. It must stay byte-for-byte
  in lock-step with the SQL pre-filter in :mod:`pricetracker_matching.alias_lookup`
  (``lower`` + fixed accent map + non-alnum→space), so it uses ``str.lower()``
  and the fixed :data:`ENSEIGNE_ACCENT_SRC`/:data:`ENSEIGNE_ACCENT_DST` map
  rather than full NFD folding.
"""

from __future__ import annotations

import re
import unicodedata

# Fixed accent-fold map, single-sourced with the SQL enseigne pre-filter in
# ``alias_lookup._SELECT_ALIASES_SQL`` (passed as bind params $3/$4). Any edit
# here MUST stay consistent with that query — that is the whole point of passing
# the map as parameters instead of duplicating a literal in the SQL.
ENSEIGNE_ACCENT_SRC = "àâäãáéèêëíìîïóòôöõúùûüýÿçñ"
ENSEIGNE_ACCENT_DST = "aaaaaeeeeiiiiooooouuuuyycn"
_ENSEIGNE_ACCENT_TABLE = str.maketrans(ENSEIGNE_ACCENT_SRC, ENSEIGNE_ACCENT_DST)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _strip_accents_nfd(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize_label(text: str | None) -> str:
    """Canonical form of a product label for exact-on-normalised matching.

    ``casefold`` → strip accents (full NFD) → collapse every run of
    non-alphanumeric characters to a single space → trim. Applied symmetrically
    to both sides of a comparison. Nothing is dropped (unlike the catalogue
    normaliser): digits and letters are preserved so ``"1.5L"`` and ``"COCA-COLA"``
    keep the tokens that make distinct products distinct.

    >>> normalize_label("PAIN COMPLET !!")
    'pain complet'
    >>> normalize_label("Café Éthiopie 250g") == normalize_label("CAFE ETHIOPIE 250G")
    True
    """
    if not text:
        return ""
    folded = _strip_accents_nfd(text.casefold())
    return _NON_ALNUM.sub(" ", folded).strip()


def enseigne_key(text: str | None) -> str:
    """Coarse canonical form of an enseigne, kept in lock-step with the SQL fold.

    ``lower`` + fixed accent map + collapse non-alnum runs to a single space +
    trim. Uses :meth:`str.lower` (not ``casefold``) and the fixed accent map so
    it matches the Postgres expression
    ``btrim(regexp_replace(translate(lower(btrim(enseigne)), src, dst), '[^a-z0-9]+', ' ', 'g'))``
    exactly.

    >>> enseigne_key("CARREFOUR MARKET")
    'carrefour market'
    >>> enseigne_key("Intermarché")
    'intermarche'
    """
    if not text:
        return ""
    folded = text.lower().translate(_ENSEIGNE_ACCENT_TABLE)
    return _NON_ALNUM.sub(" ", folded).strip()


def enseigne_candidates(enseigne: str | None) -> tuple[list[str], list[str]]:
    """Build ``(exact_forms, folded_forms)`` for the alias pre-filter query.

    - ``exact_forms`` → compared to the raw ``enseigne`` column (fast exact path
      plus the ``''`` wildcard so aliases stored without an enseigne, e.g. some
      ``user-validation`` rows, are always eligible).
    - ``folded_forms`` → compared to the SQL-folded enseigne *and* its brand
      root, so an OCR banner (``"CARREFOUR MARKET"``) still reaches catalogue
      aliases stored under a shorter brand (``"Carrefour"``), and vice-versa.

    The brand root (first token) is included only when it is at least 3 chars,
    to avoid over-broad single-letter roots (e.g. the ``"u"`` of ``"super u"``).
    """
    raw = (enseigne or "").strip()
    exact_forms = [raw, ""] if raw else [""]

    key = enseigne_key(enseigne)
    folded: list[str] = []
    if key:
        folded.append(key)
        brand_root = key.split(" ", 1)[0]
        if len(brand_root) >= 3 and brand_root != key:
            folded.append(brand_root)
    if not folded:
        folded = [""]

    # De-duplicate while preserving order (stable, deterministic bind params).
    return list(dict.fromkeys(exact_forms)), list(dict.fromkeys(folded))
