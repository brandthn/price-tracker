"""La machine a etats du decodage JSON contraint."""

import json

import pytest

from receipt_vlm.data.schema import Product, Ticket, serialize_ticket
from receipt_vlm.models.constrained import CanonicalJsonStateMachine


def _machine() -> CanonicalJsonStateMachine:
    return CanonicalJsonStateMachine()


def test_accepts_canonical_serialization() -> None:
    text = serialize_ticket(
        Ticket(
            date="20240315 14:30",
            chaine_supermarche="Monoprix",
            adresse="1 rue X, 75002 Paris",
            produits=[Product("Café moulu 250g", 3.49, 1), Product("Eau 6x1.5L", 2.99, 2)],
        )
    )
    machine = _machine()
    assert machine.feed_text(text)
    assert machine.is_complete()


def test_accepts_empty_ticket() -> None:
    machine = _machine()
    assert machine.feed_text(serialize_ticket(Ticket()))
    assert machine.is_complete()


def test_rejects_wrong_key_order() -> None:
    bad = '{"ticket":{"chaine_supermarche":"X","date":"",'
    assert not _machine().feed_text(bad)


def test_rejects_prose() -> None:
    assert not _machine().feed_text("Voici le JSON demandé : {")


def test_rejects_unquoted_string() -> None:
    assert not _machine().feed_text('{"ticket":{"date":20240315')


def test_rejects_three_decimal_price() -> None:
    machine = _machine()
    prefix = (
        '{"ticket":{"date":"","chaine_supermarche":"","adresse":"",'
        '"produits":[{"nom_produit":"X","prix_unitaire_ou_kg":1.234'
    )
    assert not machine.feed_text(prefix)


def test_rejects_zero_units() -> None:
    prefix = (
        '{"ticket":{"date":"","chaine_supermarche":"","adresse":"",'
        '"produits":[{"nom_produit":"X","prix_unitaire_ou_kg":1.00,"unites":0'
    )
    assert not _machine().feed_text(prefix)


def test_rejects_trailing_comma_in_products() -> None:
    prefix = (
        '{"ticket":{"date":"","chaine_supermarche":"","adresse":"",'
        '"produits":[{"nom_produit":"X","prix_unitaire_ou_kg":1.00,"unites":1},]'
    )
    assert not _machine().feed_text(prefix)


def test_rejects_text_after_done() -> None:
    machine = _machine()
    assert machine.feed_text(serialize_ticket(Ticket()))
    assert not machine.feed_text(" ")


def test_string_escapes() -> None:
    text = (
        '{"ticket":{"date":"","chaine_supermarche":"L\\"As des prix",'
        '"adresse":"a\\\\b \\u00e9","produits":[]}}'
    )
    machine = _machine()
    assert machine.feed_text(text)
    assert machine.is_complete()
    json.loads(text)  # au passage : le parser standard l'accepte aussi


def test_try_feed_does_not_mutate() -> None:
    machine = _machine()
    assert machine.try_feed_text('{"ticket":')
    # L'etat n'a pas bouge : le meme prefixe doit rester acceptable.
    assert machine.feed_text('{"ticket":')


def test_invalid_feed_does_not_mutate() -> None:
    machine = _machine()
    assert not machine.feed_text("nope")
    assert machine.feed_text('{"ticket":')


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7])
def test_chunked_feeding(chunk_size: int) -> None:
    """La grammaire doit accepter la cible, quelle que soit la decoupe en tokens."""
    text = serialize_ticket(Ticket(produits=[Product("Riz 1kg", 2.19, 3)]))
    machine = _machine()
    for i in range(0, len(text), chunk_size):
        assert machine.feed_text(text[i : i + chunk_size]), text[: i + chunk_size]
    assert machine.is_complete()


def test_forced_continuation_always_terminates() -> None:
    """Depuis n'importe quel prefixe, la continuation forcee doit finir par terminer."""
    text = serialize_ticket(
        Ticket(date="20240101 09:00", chaine_supermarche="Lidl",
               produits=[Product("Pain", 1.05, 1)])
    )
    for cut in range(len(text)):
        machine = _machine()
        assert machine.feed_text(text[:cut])
        steps = 0
        while not machine.is_complete():
            forced = machine.forced_continuation()
            assert forced, f"empty forced continuation at cut={cut}"
            assert machine.feed_text(forced)
            steps += 1
            assert steps < 50, f"non-terminating at cut={cut}"


def test_forced_completion_yields_valid_json() -> None:
    machine = _machine()
    partial = '{"ticket":{"date":"20240101 09:00","chaine_supermarche":"Aldi'
    assert machine.feed_text(partial)
    completed = partial
    while not machine.is_complete():
        forced = machine.forced_continuation()
        assert machine.feed_text(forced)
        completed += forced
    json.loads(completed)
