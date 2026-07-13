"""Les metriques d'evaluation."""

import pytest

from receipt_vlm.data.schema import Product, Ticket
from receipt_vlm.utils.metrics import anls, evaluate_tickets, levenshtein


def test_levenshtein_basics() -> None:
    assert levenshtein("", "") == 0
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("abc", "abd") == 1
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3


def test_anls_bounds() -> None:
    assert anls("Carrefour", "Carrefour") == 1.0
    assert anls("", "") == 1.0
    assert anls("xyz", "abc") == 0.0
    assert 0.0 < anls("Carrefour Market", "Carrefour") < 1.0


def _ticket() -> Ticket:
    return Ticket(
        date="20240315 14:30",
        chaine_supermarche="Carrefour",
        adresse="12 rue de la Paix",
        produits=[Product("Lait 1L", 1.09, 2), Product("Pain", 1.15, 1)],
    )


def test_perfect_prediction() -> None:
    metrics = evaluate_tickets([_ticket()], [_ticket()])
    assert metrics["field_f1"] == 1.0
    assert metrics["product_recall"] == 1.0
    assert metrics["price_mae"] == 0.0
    assert metrics["date_accuracy"] == 1.0
    assert metrics["anls"] == 1.0


def test_empty_prediction() -> None:
    metrics = evaluate_tickets([Ticket()], [_ticket()])
    assert metrics["field_f1"] == 0.0
    assert metrics["product_recall"] == 0.0
    assert metrics["date_accuracy"] == 0.0


def test_price_error_detected() -> None:
    pred = _ticket()
    pred.produits[0] = Product("Lait 1L", 1.59, 2)  # mauvais prix
    metrics = evaluate_tickets([pred], [_ticket()])
    assert metrics["price_mae"] == pytest.approx(0.25)
    assert metrics["product_recall"] == 1.0  # apparie quand meme, par le nom
    assert metrics["field_f1"] < 1.0


def test_fuzzy_product_matching() -> None:
    pred = _ticket()
    pred.produits[0] = Product("LAIT 1L.", 1.09, 2)  # le genre de variation que produit un OCR
    metrics = evaluate_tickets([pred], [_ticket()])
    assert metrics["product_recall"] == 1.0


def test_hallucinated_product_penalized() -> None:
    pred = _ticket()
    pred.produits.append(Product("Produit inventé", 9.99, 1))
    metrics = evaluate_tickets([pred], [_ticket()])
    assert metrics["field_precision"] < 1.0
    assert metrics["field_recall"] == 1.0


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_tickets([Ticket()], [])
