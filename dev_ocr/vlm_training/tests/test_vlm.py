"""Smoke tests for the full ReceiptVLM assembly.

Marked ``slow``: instantiation downloads CLIP ViT-B/16 and SmolLM2-360M from
the HuggingFace hub (~1.5 GB on first run). Run with ``pytest -m slow``.
"""

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from receipt_vlm.models.lora import LoRALinear, count_trainable_params  # noqa: E402

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def model():
    from receipt_vlm.models.vlm import ReceiptVLM

    vlm = ReceiptVLM(lora_rank=8)
    vlm.eval()
    return vlm


def test_param_budget(model) -> None:
    stats = count_trainable_params(model)
    assert 400_000_000 < stats["total"] < 550_000_000, stats
    # Only projector + LoRA train: a few percent at most.
    assert stats["trainable_pct"] < 5.0, stats


def test_lora_injected(model) -> None:
    lora_layers = [m for m in model.lm.modules() if isinstance(m, LoRALinear)]
    assert lora_layers, "no LoRA layers found in the decoder"


def test_forward_shapes_and_loss(model) -> None:
    pixels = torch.randn(2, 3, 224, 224)
    input_ids = torch.randint(0, 1000, (2, 12))
    labels = input_ids.clone()
    labels[:, :4] = -100
    with torch.no_grad():
        logits, loss = model(pixels, input_ids, labels=labels)
    assert logits.shape[:2] == (2, 32 + 12)
    assert loss is not None and torch.isfinite(loss)


def test_constrained_generate_emits_valid_canonical_json(model) -> None:
    """Even untrained, constrained decoding must yield parseable canonical JSON."""
    pixels = torch.randn(1, 3, 224, 224)
    outputs = model.generate(pixels, max_new_tokens=200, constrained=True)
    payload = json.loads(outputs[0])
    ticket = payload["ticket"]
    assert set(ticket) == {"date", "chaine_supermarche", "adresse", "produits"}
