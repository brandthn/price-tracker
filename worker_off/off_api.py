"""Appels HTTP à l'API Open Food Facts (produit par code-barres)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests


def fetch_product_json(base_url: str, product_code: str, timeout: float = 20.0) -> Dict[str, Any]:
    """Retourne le JSON brut de l'API OFF pour un EAN."""
    url = f"{base_url}/{product_code.strip()}"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _extract_category_levels(categories_tags: Optional[List[str]]) -> tuple[str | None, str | None, str | None]:
    """Extrait les 3 premiers niveaux de catégories OFF à partir des tags."""
    if not categories_tags:
        return None, None, None
    # Les tags OFF sont au format "fr:yaourts-nature" ou "en:dairy"
    # On garde uniquement les tags français en priorité, sinon anglais
    def _label(tag: str) -> str:
        return tag.split(":", 1)[-1].replace("-", " ").title()

    levels = [_label(t) for t in categories_tags if ":" in t]
    l1 = levels[0] if len(levels) > 0 else None
    l2 = levels[1] if len(levels) > 1 else None
    l3 = levels[2] if len(levels) > 2 else None
    return l1, l2, l3


def summarize_product(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait les champs utiles pour la table catalogueproduits."""
    status = int(payload.get("status", 0) or 0)
    product = payload.get("product") or {}

    name = (
        product.get("product_name_fr")
        or product.get("product_name")
        or None
    )
    brand = product.get("brands") or None
    if brand:
        # Prend uniquement la première marque si plusieurs (séparées par virgule)
        brand = brand.split(",")[0].strip() or None

    nutriscore = (product.get("nutriscore_grade") or "").upper() or None
    nova = str(product.get("nova_group") or "") or None
    ecoscore = (product.get("ecoscore_grade") or "").upper() or None
    image_url = product.get("image_front_url") or product.get("image_url") or None

    cat_l1, cat_l2, cat_l3 = _extract_category_levels(
        product.get("categories_tags")
    )

    return {
        "off_found":   status == 1,
        "name":        name,
        "brand":       brand,
        "category_l1": cat_l1,
        "category_l2": cat_l2,
        "category_l3": cat_l3,
        "nutriscore":  nutriscore,
        "nova":        nova,
        "ecoscore":    ecoscore,
        "image_url":   image_url,
        "raw_json":    json.dumps(payload, ensure_ascii=False),
    }
