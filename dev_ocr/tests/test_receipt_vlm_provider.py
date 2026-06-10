"""ReceiptVlmProvider guardrails and inference plumbing (mocked model)."""

from __future__ import annotations

import json

import pytest

from receipt_ocr.backends.vlm.receipt_vlm_provider import (
    ReceiptVlmProvider,
    resolve_checkpoint_path,
)
from receipt_ocr.backends.vlm.registry import build_vlm_provider
from receipt_ocr.constants import (
    ENV_VLM_MODE,
    ENV_VLM_MODEL,
    ENV_VLM_MODEL_PATH,
    VlmModelName,
    VlmMode,
)
from receipt_ocr.exceptions import OcrBackendError

CANONICAL_OUTPUT = json.dumps(
    {
        "ticket": {
            "date": "20240315 14:30",
            "chaine_supermarche": "Carrefour",
            "adresse": "",
            "produits": [
                {"nom_produit": "LAIT 1L", "prix_unitaire_ou_kg": 1.09, "unites": 1}
            ],
        }
    }
)


@pytest.fixture()
def checkpoint(tmp_path):
    path = tmp_path / "receipt_vlm_500m_merged.pt"
    path.write_bytes(b"fake checkpoint")
    return path


@pytest.fixture()
def json_mode(monkeypatch):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.JSON.value)


def test_rejects_non_json_mode(monkeypatch, checkpoint):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.TRANSCRIBE.value)
    monkeypatch.setenv(ENV_VLM_MODEL_PATH, str(checkpoint))
    with pytest.raises(OcrBackendError, match="requires RECEIPT_VLM_MODE='json'"):
        ReceiptVlmProvider()


def test_rejects_multipass_mode(monkeypatch, checkpoint):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.MULTIPASS.value)
    monkeypatch.setenv(ENV_VLM_MODEL_PATH, str(checkpoint))
    with pytest.raises(OcrBackendError, match="requires RECEIPT_VLM_MODE='json'"):
        ReceiptVlmProvider()


def test_requires_checkpoint_path(monkeypatch, json_mode):
    monkeypatch.delenv(ENV_VLM_MODEL_PATH, raising=False)
    with pytest.raises(OcrBackendError, match="RECEIPT_VLM_MODEL_PATH"):
        ReceiptVlmProvider()


def test_rejects_missing_checkpoint_file(json_mode, tmp_path):
    with pytest.raises(OcrBackendError, match="checkpoint not found"):
        ReceiptVlmProvider(model_path=str(tmp_path / "nope.pt"))


def test_resolve_checkpoint_strips_quotes(monkeypatch, checkpoint):
    monkeypatch.setenv(ENV_VLM_MODEL_PATH, f'"{checkpoint}"')
    assert resolve_checkpoint_path() == str(checkpoint)


def test_registry_builds_provider(monkeypatch, json_mode, checkpoint):
    monkeypatch.setenv(ENV_VLM_MODEL, VlmModelName.RECEIPT_VLM_500M.value)
    monkeypatch.setenv(ENV_VLM_MODEL_PATH, str(checkpoint))
    provider = build_vlm_provider()
    assert isinstance(provider, ReceiptVlmProvider)
    assert provider.model_id == VlmModelName.RECEIPT_VLM_500M.value


def test_model_is_lazy(json_mode, checkpoint):
    provider = ReceiptVlmProvider(model_path=str(checkpoint))
    assert provider._model is None  # nothing loaded at construction time


def test_analyze_returns_model_output(monkeypatch, json_mode, checkpoint, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    image_path = tmp_path / "receipt.jpg"
    Image.new("RGB", (60, 100), "white").save(image_path)

    provider = ReceiptVlmProvider(model_path=str(checkpoint), device="cpu")
    monkeypatch.setattr(
        provider, "_infer", lambda path: CANONICAL_OUTPUT, raising=True
    )
    output = provider.analyze(str(image_path), prompt="ignored")
    assert json.loads(output)["ticket"]["chaine_supermarche"] == "Carrefour"


def test_analyze_rejects_missing_image(json_mode, checkpoint):
    provider = ReceiptVlmProvider(model_path=str(checkpoint))
    with pytest.raises(Exception):
        provider.analyze("does/not/exist.jpg", prompt="")


def test_analyze_wraps_inference_errors(monkeypatch, json_mode, checkpoint, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    image_path = tmp_path / "receipt.jpg"
    Image.new("RGB", (60, 100), "white").save(image_path)

    provider = ReceiptVlmProvider(model_path=str(checkpoint))

    def boom(path):
        raise RuntimeError("CUDA exploded")

    monkeypatch.setattr(provider, "_infer", boom, raising=True)
    with pytest.raises(OcrBackendError, match="inference failed"):
        provider.analyze(str(image_path), prompt="")
