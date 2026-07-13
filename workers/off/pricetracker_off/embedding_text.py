# Embedding text builder for OFF products

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .off_client import OFFProduct

# Labels non-sémantiques (logos réglementaires / emballage) : bruit pour la reco.
# On garde tout le reste (bio, vegan, gluten-free, aop, fair-trade, ...).
_LABEL_DENYLIST = (
    "triman", "green dot", "green point", "point vert", "fsc", "pefc",
    "nutriscore", "nutri score", "ecoscore", "eco score", "eco emballage",
    "sustainable", "recycl", "tetra pak", "carton", "plastic", "glass",
    "points", "made for", "terracycle", "distributor label", "saveurs de l",
    "brevet", "medaille", "charte", "certifie par",
)

# Jetons trahissant de la métadonnée pipeline polluant `generic_name`.
_GENERIC_NAME_JUNK = ("product_id", "excatego", "recategor", "exns:")

# Scores parfois mis à tort comme CATÉGORIE par des contributeurs OFF
# (ex: "Nutri score A") — on les exclut aussi de la hiérarchie de catégories.
_CATEGORY_DENYLIST = ("nutri score", "nutriscore", "eco score", "ecoscore")


def _clean_tag(tag: str) -> str:
    #`en:dairy-desserts` / `fr:sauce-aux-piments` -> `dairy desserts` / `sauce aux piments`
    t = re.sub(r"^[a-z]{2,3}:", "", tag or "")
    return t.replace("-", " ").strip()


def _clean_categories(tags: list[str] | None) -> list[str]:
    #Hiérarchie COMPLÈTE nettoyée, dédupliquée, ordre général -> spécifique
    if not tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        c = _clean_tag(tag)
        key = c.lower()
        if not c or key in seen:
            continue
        if any(bad in key for bad in _CATEGORY_DENYLIST):
            continue  # score glissé en catégorie par un contributeur
        seen.add(key)
        out.append(c)
    return out


def _clean_labels(tags: list[str] | None, cap: int = 6) -> list[str]:
    #Labels sémantiques (bio, vegan, gluten-free, aop...) ; on écarte les logos réglementaires/emballage (denylist) Ordre d'origine, dédupliqué
    if not tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        c = _clean_tag(tag)
        key = c.lower()
        if not c or key in seen:
            continue
        if any(bad in key for bad in _LABEL_DENYLIST):
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= cap:
            break
    return out


def build_embedding_text(p: OFFProduct) -> str:
    #Build a balanced embedding text from an OFFProduct
    name = (p.name or "").strip()
    generic = (p.generic_name or "").strip()
    brand = (p.brand or "").strip()  # déjà "première marque" côté mappers
    cats = _clean_categories(p.categories_tags)
    labels = _clean_labels(p.labels_tags)
    qty = (p.quantity or "").strip()

    segments: list[str] = []
    if name:
        segments.append(name)
    gl = generic.lower()
    if (
        generic
        and gl not in name.lower()
        and name.lower() not in gl
        and not any(j in gl for j in _GENERIC_NAME_JUNK)
    ):
        segments.append(generic)
    if brand:
        segments.append(f"marque {brand}")
    if cats:
        segments.append("catégorie " + " > ".join(cats))
    if labels:
        segments.append(", ".join(labels))
    if qty:
        segments.append(qty)
    return ". ".join(segments).strip() or (p.ean or "")
