from __future__ import annotations

import pytest

from pricetracker_off.quantity import normalize_quantity


@pytest.mark.parametrize(
    ("qty", "unit", "expected_value", "expected_unit"),
    [
        # masse → kg
        ("500", "g", 0.5, "kg"),
        (263.99, "g", 0.26399, "kg"),
        ("1", "kg", 1.0, "kg"),
        ("500", "mg", 0.0005, "kg"),
        # volume → L
        ("1000", "ml", 1.0, "L"),
        ("750", "ml", 0.75, "L"),
        ("33", "cl", 0.33, "L"),
        ("1.5", "l", 1.5, "L"),
        # casse / espaces tolérés sur l'unité (source unique de vérité)
        ("500", " G ", 0.5, "kg"),
        ("1000", "ML", 1.0, "L"),
    ],
)
def test_normalize_known_units(qty, unit, expected_value, expected_unit) -> None:
    value, canonical = normalize_quantity(qty, unit)
    assert canonical == expected_unit
    assert value == pytest.approx(expected_value)


@pytest.mark.parametrize(
    ("qty", "unit"),
    [
        (None, "g"),          # pas de valeur
        ("500", None),        # pas d'unité
        ("500", ""),          # unité vide
        ("500", "%"),         # unité junk (vue dans le dump)
        ("500", "kj"),        # unité junk
        ("500", "piece"),     # pas de dimension pièce dans OFF product_quantity
        ("500", "oz"),        # unité non gérée (jamais devinée)
        ("abc", "g"),         # non parsable
        ("0", "g"),           # valeur nulle → exclu
        ("-100", "g"),        # valeur négative → exclu
        ("", "g"),            # texte vide
    ],
)
def test_normalize_excluded(qty, unit) -> None:
    assert normalize_quantity(qty, unit) == (None, None)
