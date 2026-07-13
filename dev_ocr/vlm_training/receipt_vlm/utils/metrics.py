"""Metriques d'eval : F1 par champ, ANLS, MAE des prix, rappel produit, date exacte.

Tout travaille sur des paires de Ticket canoniques, donc le meme code note le modele
maison et la baseline Groq.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from receipt_vlm.data.schema import Product, Ticket


def levenshtein(a, b) -> int:
    """Distance d'edition. Marche sur des chaines comme sur des listes de mots."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(min(
                previous[j] + 1,        # deletion
                current[j - 1] + 1,     # insertion
                previous[j - 1] + cost  # substitution
            ))
        previous = current
    return previous[-1]


def anls(prediction: str, target: str) -> float:
    """Average Normalized Levenshtein Similarity for one string pair (0..1)."""
    pred = prediction.strip().lower()
    gold = target.strip().lower()
    if not pred and not gold:
        return 1.0
    denominator = max(len(pred), len(gold))
    if denominator == 0:
        return 1.0
    return 1.0 - levenshtein(pred, gold) / denominator


def _match_products(
    predicted: list[Product],
    gold: list[Product],
    name_threshold: float = 0.7,
) -> list[tuple[Product, Product]]:
    """Greedy 1:1 matching of product lines by name similarity."""
    pairs: list[tuple[Product, Product]] = []
    remaining = list(predicted)
    for gold_product in gold:
        best, best_score = None, name_threshold
        for candidate in remaining:
            score = anls(candidate.nom_produit, gold_product.nom_produit)
            if score >= best_score:
                best, best_score = candidate, score
        if best is not None:
            pairs.append((best, gold_product))
            remaining.remove(best)
    return pairs


@dataclass
class _Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    price_errors: list[float] = field(default_factory=list)
    anls_scores: list[float] = field(default_factory=list)
    date_total: int = 0
    date_correct: int = 0
    products_gold: int = 0
    products_matched: int = 0


def _score_pair(pred: Ticket, gold: Ticket, counts: _Counts) -> None:
    # Champs scalaires : le match exact compte dans le F1, si la valeur de reference existe.
    for pred_value, gold_value in (
        (pred.date, gold.date),
        (pred.chaine_supermarche.lower(), gold.chaine_supermarche.lower()),
        (pred.adresse.lower(), gold.adresse.lower()),
    ):
        if gold_value:
            counts.anls_scores.append(anls(pred_value, gold_value))
            if pred_value == gold_value:
                counts.tp += 1
            else:
                counts.fn += 1
                if pred_value:
                    counts.fp += 1
        elif pred_value:
            counts.fp += 1

    if gold.date:
        counts.date_total += 1
        if pred.date == gold.date:
            counts.date_correct += 1

    # Product lines: greedy name matching, then price/units agreement.
    pairs = _match_products(pred.produits, gold.produits)
    counts.products_gold += len(gold.produits)
    counts.products_matched += len(pairs)
    for pred_product, gold_product in pairs:
        counts.anls_scores.append(
            anls(pred_product.nom_produit, gold_product.nom_produit)
        )
        price_error = abs(
            pred_product.prix_unitaire_ou_kg - gold_product.prix_unitaire_ou_kg
        )
        counts.price_errors.append(price_error)
        exact = price_error < 0.005 and pred_product.unites == gold_product.unites
        if exact:
            counts.tp += 1
        else:
            counts.fp += 1
            counts.fn += 1
    counts.fn += len(gold.produits) - len(pairs)
    counts.fp += len(pred.produits) - len(pairs)


def evaluate_tickets(predictions: list[Ticket], golds: list[Ticket]) -> dict[str, float]:
    """Aggregate metrics over a list of (prediction, gold) ticket pairs."""
    if len(predictions) != len(golds):
        raise ValueError("predictions and golds must have the same length")

    counts = _Counts()
    for pred, gold in zip(predictions, golds):
        _score_pair(pred, gold, counts)

    precision = counts.tp / (counts.tp + counts.fp) if counts.tp + counts.fp else 0.0
    recall = counts.tp / (counts.tp + counts.fn) if counts.tp + counts.fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "field_f1": f1,
        "field_precision": precision,
        "field_recall": recall,
        "anls": (
            sum(counts.anls_scores) / len(counts.anls_scores)
            if counts.anls_scores
            else 0.0
        ),
        "price_mae": (
            sum(counts.price_errors) / len(counts.price_errors)
            if counts.price_errors
            else 0.0
        ),
        "product_recall": (
            counts.products_matched / counts.products_gold
            if counts.products_gold
            else 0.0
        ),
        "date_accuracy": (
            counts.date_correct / counts.date_total if counts.date_total else 0.0
        ),
        "n_samples": float(len(golds)),
    }
