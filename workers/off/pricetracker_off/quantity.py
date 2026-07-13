#Normalisation quantité OFF → unité canonique (kg / L) pour le €/unité

from __future__ import annotations

_MASS_TO_KG: dict[str, float] = {"mg": 1e-6, "g": 1e-3, "kg": 1.0}
_VOLUME_TO_L: dict[str, float] = {"ml": 1e-3, "cl": 1e-2, "l": 1.0, "liter": 1.0, "litre": 1.0}


def normalize_quantity(
    product_quantity: str | float | int | None,
    product_quantity_unit: str | None,
) -> tuple[float | None, str | None]:
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
