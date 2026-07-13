from __future__ import annotations

import sys
from pathlib import Path

from pricetracker_off.embedding_text import build_embedding_text
from pricetracker_off.off_client import OFFProduct, _to_off_product

# `bulk/enrich.py` vit hors du wheel ; on l'ajoute au path pour tester le mapper
# dump. `import duckdb` y est paresseux (dans fetch_from_parquet) → import OK ici.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bulk.enrich import _row_to_product


def _p(**kw: object) -> OFFProduct:
    base: dict[str, object] = {
        "ean": "X", "name": None, "brand": None,
        "category_l1": None, "category_l2": None, "category_l3": None,
        "nutriscore": None, "nova": None, "ecoscore": None,
        "image_url": None, "found": True,
    }
    base.update(kw)
    return OFFProduct(**base)  # type: ignore[arg-type]


def test_full_formula_order_and_cleaning() -> None:
    p = _p(
        name="Crème brûlée à la vanille",
        generic_name="Dessert lacté",
        brand="Bonne Maman",
        categories_tags=["en:dairies", "en:dairy-desserts", "en:creme-brulee"],
        labels_tags=["en:organic"],
        quantity="100 g",
    )
    assert build_embedding_text(p) == (
        "Crème brûlée à la vanille. Dessert lacté. marque Bonne Maman. "
        "catégorie dairies > dairy desserts > creme brulee. organic. 100 g"
    )


def test_label_denylist_drops_regulatory_logos() -> None:
    p = _p(name="Yaourt", labels_tags=["en:green-dot", "en:triman", "en:organic", "en:nutriscore"])
    txt = build_embedding_text(p)
    assert "organic" in txt
    assert "green" not in txt and "triman" not in txt and "nutriscore" not in txt


def test_category_denylist_drops_scores_as_category() -> None:
    p = _p(name="Soda", categories_tags=["en:beverages", "en:nutriscore-e"])
    txt = build_embedding_text(p)
    assert "beverages" in txt
    assert "nutriscore" not in txt


def test_generic_name_dropped_when_redundant_with_name() -> None:
    # generic == name (à la casse près) → non ajouté (pas de doublon)
    p = _p(name="Lait demi-écrémé", generic_name="lait demi-écrémé")
    assert build_embedding_text(p) == "Lait demi-écrémé"


def test_generic_name_pipeline_junk_dropped() -> None:
    p = _p(name="Truc", generic_name="excatego product_id 42")
    assert build_embedding_text(p) == "Truc"


def test_scores_excluded_from_text() -> None:
    # nutriscore/nova/ecoscore ne doivent JAMAIS entrer dans le texte d'embedding
    p = _p(name="Pizza", nutriscore="D", nova="4", ecoscore="C")
    assert build_embedding_text(p) == "Pizza"


def test_fallback_to_ean_when_empty() -> None:
    assert build_embedding_text(_p(ean="0000000001")) == "0000000001"


# --- PARITÉ API ↔ dump ------------------------------------------------------

def _api_payload() -> dict:
    return {
        "status": 1,
        "product": {
            "product_name_fr": "Crème brûlée à la vanille",
            "generic_name_fr": "Dessert lacté",
            "brands": "Bonne Maman, Andros",
            "categories_tags": ["en:dairies", "en:dairy-desserts", "en:creme-brulee"],
            "labels_tags": ["en:organic", "en:green-dot"],
            "quantity": "100 g",
        },
    }


def _dump_row() -> dict:
    # Schéma DuckDB de bulk/enrich._QUERY : product_name/generic_name en STRUCT(lang,text)[].
    return {
        "ean": "3033710065608",
        "product_name": [{"lang": "fr", "text": "Crème brûlée à la vanille"}],
        "generic_name": [{"lang": "fr", "text": "Dessert lacté"}],
        "brands": "Bonne Maman, Andros",
        "categories_tags": ["en:dairies", "en:dairy-desserts", "en:creme-brulee"],
        "labels_tags": ["en:organic", "en:green-dot"],
        "quantity": "100 g",
        "nutriscore_grade": None,
        "nova_group": None,
        "ecoscore_grade": None,
        "images": None,
    }


def test_parity_api_vs_dump_same_embedding_text() -> None:
    p_api = _to_off_product("3033710065608", _api_payload())
    p_dump = _row_to_product(_dump_row())
    txt_api = build_embedding_text(p_api)
    txt_dump = build_embedding_text(p_dump)
    assert txt_api == txt_dump
    # et le contenu attendu (green-dot filtré, marque = première, hiérarchie complète)
    assert txt_api == (
        "Crème brûlée à la vanille. Dessert lacté. marque Bonne Maman. "
        "catégorie dairies > dairy desserts > creme brulee. organic. 100 g"
    )
