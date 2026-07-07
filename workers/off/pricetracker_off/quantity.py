"""Normalisation quantité OFF → unité canonique (kg / L) pour le €/unité.

SOURCE UNIQUE de vérité (même logique de parité API↔dump que `embedding_text`) :
les deux voies d'acquisition passent les champs OFF bruts
`product_quantity` (VARCHAR numérique, déjà exprimé en g ou ml chez OFF) +
`product_quantity_unit` (`g` | `ml`), et cette fonction en dérive la paire
`(valeur, unité canonique)` utilisée pour comparer au €/kg ou €/L.

Décision ferme (§5.2 handoff) : **AUCUN regex, AUCUNE inférence** depuis le texte
libre `quantity` (« 6x33cl », « lot de 2 » → parses faux → faux €/unité → fausse
promo). Une unité non reconnue → `(None, None)` = produit **exclu** du calcul
d'économie (échec sûr), jamais un €/unité deviné (échec dangereux). Il reste
visible via l'endpoint substituts sémantique, mais sans chiffre d'économie.

Vérifié sur le dump OFF (4,58 M produits) : `product_quantity_unit` ne vaut en
pratique que `g` / `ml` — OFF normalise déjà. `kg`/`l`/`cl`/`mg` sont tolérés par
robustesse au cas où l'API OFF les renverrait (unité *explicite*, pas devinée).
Aucune dimension « pièce » n'existe dans les données OFF `product_quantity` → non
produite ici (elle exigerait un parsing texte interdit).
"""

from __future__ import annotations

# Facteur vers l'unité canonique de la dimension. La comparaison €/unité en
# Étape 2 ne se fait qu'entre unités identiques (kg↔kg, L↔L).
_MASS_TO_KG: dict[str, float] = {"mg": 1e-6, "g": 1e-3, "kg": 1.0}
_VOLUME_TO_L: dict[str, float] = {"ml": 1e-3, "cl": 1e-2, "l": 1.0, "liter": 1.0, "litre": 1.0}


def normalize_quantity(
    product_quantity: str | float | int | None,
    product_quantity_unit: str | None,
) -> tuple[float | None, str | None]:
    """`(valeur_canonique, 'kg'|'L')` ou `(None, None)` si non exploitable.

    - `product_quantity` doit se parser en float **strictement positif** ;
    - `product_quantity_unit` doit être une unité de masse (→ kg) ou de volume
      (→ L). Toute autre unité (`%`, `kj`, vide, pièce, `oz`…) → exclu.
    """
    if product_quantity is None:
        return None, None
    try:
        value = float(product_quantity)
    except (TypeError, ValueError):
        return None, None
    if not value > 0:
        return None, None

    unit = (product_quantity_unit or "").strip().lower()
    if unit in _MASS_TO_KG:
        return value * _MASS_TO_KG[unit], "kg"
    if unit in _VOLUME_TO_L:
        return value * _VOLUME_TO_L[unit], "L"
    return None, None
