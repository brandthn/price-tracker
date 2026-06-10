"""Tests for the synthetic French receipt generator."""

import json

import pytest

pytest.importorskip("PIL")

from receipt_vlm.data.schema import ticket_from_dict  # noqa: E402
from receipt_vlm.data.synthetic import (  # noqa: E402
    generate_ticket,
    load_dataset,
    render_receipt_image,
    save_dataset,
)
from receipt_vlm.models.constrained import CanonicalJsonStateMachine  # noqa: E402
from receipt_vlm.data.schema import serialize_ticket  # noqa: E402


def test_generate_ticket_deterministic_with_seed() -> None:
    assert generate_ticket(seed=42) == generate_ticket(seed=42)


def test_generate_ticket_valid_canonical() -> None:
    for seed in range(25):
        ticket = generate_ticket(seed=seed)
        assert ticket.chaine_supermarche
        assert 3 <= len(ticket.produits) <= 14
        for product in ticket.produits:
            assert product.nom_produit
            assert product.prix_unitaire_ou_kg > 0
            assert product.unites >= 1
        if ticket.date:
            assert len(ticket.date) == 14  # yyyyMMdd HH:mm
        # Labels must be accepted by the constrained-decoding grammar.
        machine = CanonicalJsonStateMachine()
        assert machine.feed_text(serialize_ticket(ticket))
        assert machine.is_complete()


def test_render_produces_image() -> None:
    ticket = generate_ticket(seed=7)
    image = render_receipt_image(ticket, seed=7)
    assert image.size[0] == 420
    assert image.size[1] > 200


def test_save_and_load_roundtrip(tmp_path) -> None:
    paths = save_dataset(3, tmp_path, seed=123)
    assert len(paths) == 3
    assert all(p.exists() for p in paths)

    samples = load_dataset(tmp_path)
    assert len(samples) == 3
    for image_path, ticket in samples:
        label = json.loads(image_path.with_suffix(".json").read_text("utf-8"))
        assert ticket == ticket_from_dict(label)
