"""Formule d'embedding « balanced » — SOURCE UNIQUE de vérité.

Ce module centralise `build_embedding_text` (auparavant dupliqué dans
`bulk/enrich.py`) pour que le **worker quotidien** (`main.py`, via l'API OFF)
ET le **bulk** (`bulk/enrich.py`, via le dump OFF) produisent EXACTEMENT le
même texte pour un même produit. Sinon l'espace vectoriel re-diverge (le worker
ré-injecterait du legacy à chaque nouvel EAN).

Contrat d'entrée : un `OFFProduct` dont les mappers (`off_client._to_off_product`
côté API, `bulk/enrich._row_to_product` côté dump) ont NORMALISÉ à l'identique :
  - `name` / `generic_name` : str (fr>main>en côté dump, *_fr>* côté API) ;
  - `brand` : première marque (split ','), str ;
  - `categories_tags` / `labels_tags` : listes brutes préfixées `en:`/`fr:`
    (même format dans le dump et via l'API) — nettoyées ici ;
  - `quantity` : str.

Signal sémantique **positif** uniquement, optimisé pour la reco de substituts :
`name . generic_name . marque <brand> . catégorie <hiérarchie COMPLÈTE> . <labels> . <quantité>`
Exclut volontairement nutriscore/nova/ecoscore (scores ordinaux → colonnes de
filtrage), ingrédients et allergènes (bruit / dilution).
"""

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
    """`en:dairy-desserts` / `fr:sauce-aux-piments` -> `dairy desserts` / `sauce aux piments`."""
    t = re.sub(r"^[a-z]{2,3}:", "", tag or "")
    return t.replace("-", " ").strip()


def _clean_categories(tags: list[str] | None) -> list[str]:
    """Hiérarchie COMPLÈTE nettoyée, dédupliquée, ordre général -> spécifique."""
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
    """Labels sémantiques (bio, vegan, gluten-free, aop...) ; on écarte les
    logos réglementaires/emballage (denylist). Ordre d'origine, dédupliqué."""
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
    """Texte d'embedding 'balanced' à partir d'un `OFFProduct` déjà normalisé.

    Idempotent vis-à-vis de la source (API OFF vs dump) : la seule différence
    entre les deux — les champs multilingues `product_name`/`generic_name` — est
    résolue en amont par les mappers, donc ce texte est identique pour un même
    produit quelle que soit la voie d'acquisition.
    """
    name = (p.name or "").strip()
    generic = (p.generic_name or "").strip()
    brand = (p.brand or "").strip()  # déjà "première marque" côté mappers
    cats = _clean_categories(p.categories_tags)
    labels = _clean_labels(p.labels_tags)
    qty = (p.quantity or "").strip()

    segments: list[str] = []
    if name:
        segments.append(name)
    # generic_name seulement s'il apporte de l'info (pas un doublon du nom,
    # pas de la métadonnée pipeline polluante)
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
