"""Le schema canonique et son serialiseur deterministe."""

import json

from receipt_vlm.data.schema import (
    Product,
    Ticket,
    serialize_ticket,
    ticket_from_dict,
    ticket_from_json,
)


def _sample_ticket() -> Ticket:
    return Ticket(
        date="20240315 14:30",
        chaine_supermarche="Carrefour Market",
        adresse="12 rue de la Paix, 75001 Paris",
        produits=[
            Product("Lait demi-écrémé 1L", 1.09, 2),
            Product("Pâtes spaghetti 500g", 0.99, 1),
        ],
    )


def test_serialize_is_valid_json() -> None:
    payload = json.loads(serialize_ticket(_sample_ticket()))
    ticket = payload["ticket"]
    assert ticket["date"] == "20240315 14:30"
    assert ticket["chaine_supermarche"] == "Carrefour Market"
    assert len(ticket["produits"]) == 2
    assert ticket["produits"][0]["prix_unitaire_ou_kg"] == 1.09
    assert ticket["produits"][0]["unites"] == 2


def test_serialize_two_decimal_prices() -> None:
    text = serialize_ticket(Ticket(produits=[Product("X", 1.1, 1)]))
    assert '"prix_unitaire_ou_kg":1.10' in text


def test_serialize_deterministic() -> None:
    assert serialize_ticket(_sample_ticket()) == serialize_ticket(_sample_ticket())


def test_serialize_keeps_accents() -> None:
    text = serialize_ticket(_sample_ticket())
    assert "écrémé" in text
    assert "\\u00e9" not in text


def test_empty_ticket() -> None:
    payload = json.loads(serialize_ticket(Ticket()))
    assert payload == {
        "ticket": {"date": "", "chaine_supermarche": "", "adresse": "", "produits": []}
    }


def test_roundtrip() -> None:
    original = _sample_ticket()
    parsed = ticket_from_json(serialize_ticket(original))
    assert parsed == original


def test_from_dict_coercions() -> None:
    ticket = ticket_from_dict(
        {
            "ticket": {
                "date": None,
                "produits": [
                    {"nom_produit": "OK", "prix_unitaire_ou_kg": "2.5", "unites": 0},
                    {"nom_produit": "", "prix_unitaire_ou_kg": 1.0},
                    "garbage",
                ],
            }
        }
    )
    assert ticket.date == ""
    assert len(ticket.produits) == 1
    assert ticket.produits[0].prix_unitaire_ou_kg == 2.5
    assert ticket.produits[0].unites == 1  # ramene a 1 au minimum


def test_from_dict_accepts_bare_inner() -> None:
    ticket = ticket_from_dict({"chaine_supermarche": "Lidl", "produits": []})
    assert ticket.chaine_supermarche == "Lidl"
