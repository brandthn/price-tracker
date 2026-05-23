"""Enrichissements post-cleaner : normalisation enseigne, ville, EAN, IQR.

Différences vs `local_pipeline/silver_enrichments.py` du collègue :
- Pas de dépendance pandas. `flag_iqr_outliers` réécrit en numpy pur — le
  worker importe déjà numpy via pyarrow, on évite une lourde dep transitives.
- `validate_ean` et `check_discount_coherence` retournent `(bool, str | None)`
  pour s'aligner sur le pattern du cleaner et permettre un bucketing rejection
  homogène côté `transform.py`.
- Patterns d'enseignes pré-compilés au module load (gain perf sur 10⁶ lignes).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# 1. Normalisation enseigne
# ---------------------------------------------------------------------------
#
# Liste ordonnée du plus spécifique au plus général : "Carrefour Market"
# AVANT "Carrefour" sinon le second matche le premier et écrase. Les patterns
# sont insensibles à la casse (re.IGNORECASE compilé une fois).

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
    """Extrait l'enseigne canonique depuis l'adresse OSM brute.

    Si aucune enseigne connue ne matche, retourne le premier segment avant
    la virgule (= nom du POI OSM), tronqué à 80 caractères. Évite des
    valeurs `store_brand_normalized` à NULL alors qu'on a quand même un nom
    de magasin partiellement utilisable.
    """
    if not raw:
        return None
    for pattern, canonical in _COMPILED_BRAND_PATTERNS:
        if pattern.search(raw):
            return canonical
    first_segment = raw.split(",")[0].strip()
    return first_segment[:80] if first_segment else None


# ---------------------------------------------------------------------------
# 2. Standardisation ville
# ---------------------------------------------------------------------------

_ARRONDISSEMENT_PATTERN = re.compile(
    r"\s+\d+\s*(e|er|[èe]me|i[èe]me)?\s*(arrondissement)?$",
    re.IGNORECASE,
)


def standardize_city(raw: str | None) -> str | None:
    """Normalise le nom de ville (title-case, supprime suffixe d'arrondissement)."""
    if not raw:
        return None
    city = raw.strip()
    if not city:
        return None
    city = city.title()
    city = _ARRONDISSEMENT_PATTERN.sub("", city).strip()
    return city or None


# ---------------------------------------------------------------------------
# 3. Validation EAN-13 / EAN-8
# ---------------------------------------------------------------------------


def validate_ean(product_code: str | None) -> tuple[bool, str | None]:
    """Vérifie longueur + checksum modulo 10 (EAN-13 ou EAN-8).

    Retourne (True, None) si valide, sinon (False, details).
    """
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


# ---------------------------------------------------------------------------
# 4. Cohérence prix remisé
# ---------------------------------------------------------------------------


def check_discount_coherence(row: dict[str, Any]) -> tuple[bool, str | None]:
    """Vérifie qu'un prix marqué en promo a un `price_without_discount` cohérent.

    Règles :
    - `price_is_discounted=False/None` → toujours cohérent (rien à vérifier).
    - `price_is_discounted=True` ET `price_without_discount_eur=None` → on tolère
      (l'enseigne n'a pas saisi le prix d'origine, courant en GMS). Pas un rejet.
    - `price_is_discounted=True` ET prix d'origine ≤ prix remisé → INCOHERENT.
    - Remise > 95% → suspect (saisie probablement erronée) → INCOHERENT.
    """
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


# ---------------------------------------------------------------------------
# 5. Flag IQR outliers (post-pass, group-by product_code)
# ---------------------------------------------------------------------------


def flag_iqr_outliers(rows: list[dict[str, Any]], *, iqr_multiplier: float = 3.0) -> None:
    """Annote chaque row avec `iqr_outlier: bool` (mutation in-place).

    Pour chaque `product_code` ayant ≥ 5 observations, calcule Q1/Q3 sur
    `price_eur` et flag les valeurs hors [Q1 - k·IQR, Q3 + k·IQR]. Pour les
    EAN avec < 5 observations, on ne peut pas calculer un quartile fiable →
    `iqr_outlier = False` par défaut (innocent par manque de preuve).

    `iqr_multiplier=3` (plus large que le 1.5 classique) car les promotions
    légitimes et les produits premium peuvent légitimement s'écarter — on veut
    flag uniquement les saisies clairement aberrantes (ex: lait à 999€).

    Implémenté en numpy pur (pas de pandas) pour rester dans la dep stack
    pyarrow déjà présente.
    """
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

    # Toute ligne sans product_code (ne devrait pas arriver post-cleaner mais
    # garde-fou) : iqr_outlier = False.
    for r in rows:
        r.setdefault("iqr_outlier", False)
