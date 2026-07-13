

from __future__ import annotations

import re
import unicodedata


ENSEIGNE_ACCENT_SRC = "àâäãáéèêëíìîïóòôöõúùûüýÿçñ"
ENSEIGNE_ACCENT_DST = "aaaaaeeeeiiiiooooouuuuyycn"
_ENSEIGNE_ACCENT_TABLE = str.maketrans(ENSEIGNE_ACCENT_SRC, ENSEIGNE_ACCENT_DST)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _strip_accents_nfd(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize_label(text: str | None) -> str:

    if not text:
        return ""
    folded = _strip_accents_nfd(text.casefold())
    return _NON_ALNUM.sub(" ", folded).strip()


def enseigne_key(text: str | None) -> str:

    if not text:
        return ""
    folded = text.lower().translate(_ENSEIGNE_ACCENT_TABLE)
    return _NON_ALNUM.sub(" ", folded).strip()


def enseigne_candidates(enseigne: str | None) -> tuple[list[str], list[str]]:

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


    return list(dict.fromkeys(exact_forms)), list(dict.fromkeys(folded))
