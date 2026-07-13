
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import numpy as np



_BRAND_PATTERNS: list[tuple[str, str]] = [
    (r"e\.?\s*leclerc|centre\s+commercial\s+e\.?\s*leclerc", "E.Leclerc"),
    (r"carrefour\s+city", "Carrefour City"),
    (r"carrefour\s+market", "Carrefour Market"),
    (r"carrefour\s+express", "Carrefour Express"),
    (r"carrefour\s+contact", "Carrefour Contact"),
    (r"\bcarrefour\b", "Carrefour"),
    (r"auchan\s+supermarch[ée]", "Auchan Supermarché"),
    (r"auchan\s+hypermarch[ée]", "Auchan Hypermarché"),
    (r"\bauchan\b", "Auchan"),
    (r"intermarch[ée]", "Intermarché"),
    (r"hyper\s+u\b", "Hyper U"),
    (r"u\s+express\b", "U Express"),
    (r"super\s+u\b", "Super U"),
    (r"\bu\s+marche[é]\b", "U Marché"),
    (r"\blidl\b", "Lidl"),
    (r"\baldi\b", "Aldi"),
    (r"monop['’]", "Monoprix"),
    (r"\bmonoprix\b", "Monoprix"),
    (r"\bfranprix\b", "Franprix"),
    (r"g[ée]ant\s+casino", "Géant Casino"),
    (r"\bcasino\b", "Casino"),
    (r"\bnetto\b", "Netto"),
    (r"\bbiocoop\b", "Biocoop"),
    (r"la\s+vie\s+claire", "La Vie Claire"),
    (r"\bpicard\b", "Picard"),
    (r"\baction\b", "Action"),
    (r"grand\s+frais", "Grand Frais"),
    (r"\bcora\b", "Cora"),
    (r"\bmatch\b", "Match"),
]
_COMPILED_BRAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), name) for p, name in _BRAND_PATTERNS
]


def normalize_store_brand(raw: str | None) -> str | None:

    if not raw:
        return None
    for pattern, canonical in _COMPILED_BRAND_PATTERNS:
        if pattern.search(raw):
            return canonical
    first_segment = raw.split(",")[0].strip()
    return first_segment[:80] if first_segment else None




_ARRONDISSEMENT_PATTERN = re.compile(
    r"\s+\d+\s*(e|er|[èe]me|i[èe]me)?\s*(arrondissement)?$",
    re.IGNORECASE,
)


def standardize_city(raw: str | None) -> str | None:

    if not raw:
        return None
    city = raw.strip()
    if not city:
        return None
    city = city.title()
    city = _ARRONDISSEMENT_PATTERN.sub("", city).strip()
    return city or None





def validate_ean(product_code: str | None) -> tuple[bool, str | None]:

    if not product_code:
        return False, "product_code vide"
    code = str(product_code).strip()
    if not code.isdigit():
        return False, f"contient des caracteres non numeriques: {code!r}"
    if len(code) == 8:
        digits = [int(d) for d in code]
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        expected = (10 - (total % 10)) % 10
        if digits[-1] != expected:
            return False, f"checksum EAN-8 invalide (attendu {expected}, recu {digits[-1]})"
        return True, None
    if len(code) == 13:
        digits = [int(d) for d in code]
        total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[:-1]))
        expected = (10 - (total % 10)) % 10
        if digits[-1] != expected:
            return False, f"checksum EAN-13 invalide (attendu {expected}, recu {digits[-1]})"
        return True, None
    return False, f"longueur EAN invalide: {len(code)} chiffres (attendu 8 ou 13)"





def check_discount_coherence(row: dict[str, Any]) -> tuple[bool, str | None]:

    if not row.get("price_is_discounted"):
        return True, None
    price = row.get("price_eur")
    full_price = row.get("price_without_discount_eur")
    if full_price is None or price is None:
        return True, None
    if full_price <= price:
        return False, f"prix remisé ({price}€) ≥ prix sans remise ({full_price}€)"
    if (full_price - price) / full_price > 0.95:
        return False, f"remise > 95% : {price}€ vs {full_price}€"
    return True, None





def flag_iqr_outliers(rows: list[dict[str, Any]], *, iqr_multiplier: float = 3.0) -> None:

    if not rows:
        return

    by_code: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        code = r.get("product_code")
        if code:
            by_code[code].append(i)

    for code, indices in by_code.items():
        if len(indices) < 5:
            for i in indices:
                rows[i]["iqr_outlier"] = False
            continue
        prices = np.fromiter((rows[i]["price_eur"] for i in indices), dtype=np.float64)
        q1, q3 = np.percentile(prices, [25, 75])
        iqr = q3 - q1
        lower = q1 - iqr_multiplier * iqr
        upper = q3 + iqr_multiplier * iqr
        for i in indices:
            p = rows[i]["price_eur"]
            rows[i]["iqr_outlier"] = bool(p < lower or p > upper)


    for r in rows:
        r.setdefault("iqr_outlier", False)
