"""Le generateur de tickets synthetiques."""

import json

import pytest

pytest.importorskip("PIL")

from receipt_vlm.data.schema import serialize_ticket, ticket_from_dict  # noqa: E402
from receipt_vlm.data.synthetic import (  # noqa: E402
    _LAYOUT_STYLES,
    distort_receipt_image,
    generate_ticket,
    load_dataset,
    render_receipt_image,
    save_dataset,
)
from receipt_vlm.models.constrained import CanonicalJsonStateMachine  # noqa: E402


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


def test_diverse_renders_vary_in_size() -> None:
    sizes = {render_receipt_image(generate_ticket(seed=i), seed=i, diverse=True).size for i in range(30)}
    assert len(sizes) > 5, "diverse mode should produce multiple canvas sizes"


def test_distort_changes_pixels() -> None:
    base = render_receipt_image(generate_ticket(seed=1), seed=1, diverse=True)
    warped = render_receipt_image(
        generate_ticket(seed=1), seed=1, diverse=True, distort=True, distort_intensity="heavy"
    )
    assert base.size != warped.size or list(base.getdata()) != list(warped.getdata())


def test_distort_standalone() -> None:
    clean = render_receipt_image(generate_ticket(seed=5), seed=5)
    noisy = distort_receipt_image(clean, seed=99, intensity="heavy")
    assert noisy.size[0] >= clean.size[0] * 0.5


def test_diverse_save_produces_valid_labels(tmp_path) -> None:
    paths = save_dataset(5, tmp_path, seed=77, diverse=True, distort=True)
    assert len(paths) == 5
    for path in paths:
        ticket = ticket_from_dict(json.loads(path.with_suffix(".json").read_text()))
        machine = CanonicalJsonStateMachine()
        assert machine.feed_text(serialize_ticket(ticket))


def test_layout_styles_defined() -> None:
    assert len(_LAYOUT_STYLES) >= 6


def test_build_live_synthetic_samples() -> None:
    from receipt_vlm.data.samples import build_live_synthetic_samples

    samples = build_live_synthetic_samples(8, seed=0, diverse=True, distort=True)
    assert len(samples) == 8
    assert all(s.source == "synthetic_live")
    assert callable(samples[0].image)
    img = samples[0].image()
    assert img.size[0] > 100
