"""Shape and gradient tests for the from-scratch multimodal projector."""

import pytest

torch = pytest.importorskip("torch")

from receipt_vlm.models.projector import MultimodalProjector  # noqa: E402


def test_output_shape_default_dims() -> None:
    projector = MultimodalProjector(vision_dim=768, lang_dim=960, num_patches=197)
    x = torch.randn(2, 197, 768)
    out = projector(x)
    assert out.shape == (2, 32, 960)


def test_output_shape_custom_queries() -> None:
    projector = MultimodalProjector(
        vision_dim=64, lang_dim=48, num_patches=10, num_queries=8, num_heads=4
    )
    out = projector(torch.randn(3, 10, 64))
    assert out.shape == (3, 8, 48)


def test_gradients_flow() -> None:
    projector = MultimodalProjector(
        vision_dim=32, lang_dim=16, num_patches=5, num_queries=4, num_heads=2
    )
    out = projector(torch.randn(1, 5, 32))
    out.sum().backward()
    for name, param in projector.named_parameters():
        assert param.grad is not None, f"no gradient for {name}"


def test_all_params_trainable() -> None:
    projector = MultimodalProjector()
    assert all(p.requires_grad for p in projector.parameters())


def test_param_budget() -> None:
    """Projector stays small (~7M at lang_dim=960; spec's ~12-15M assumed 1024+)."""
    projector = MultimodalProjector(vision_dim=768, lang_dim=960, num_patches=197)
    n_params = sum(p.numel() for p in projector.parameters())
    assert 4_000_000 < n_params < 20_000_000, n_params
