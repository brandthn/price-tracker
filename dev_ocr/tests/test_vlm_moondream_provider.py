"""Tests for MoondreamProvider (mocked — no real model weights)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from receipt_ocr.backends.vlm.moondream_provider import (
    MoondreamProvider,
    resolve_moondream_model_path,
)
from receipt_ocr.constants import ENV_VLM_MODEL_PATH
from receipt_ocr.exceptions import OcrBackendError


def test_resolve_moondream_model_path_explicit(tmp_path):
    model_file = tmp_path / "moondream-0_5b-int8.mf"
    model_file.write_bytes(b"weights")
    assert resolve_moondream_model_path(model_file) == model_file


def test_resolve_moondream_model_path_env(monkeypatch, tmp_path):
    model_file = tmp_path / "custom.mf"
    model_file.write_bytes(b"weights")
    monkeypatch.setenv(ENV_VLM_MODEL_PATH, str(model_file))
    assert resolve_moondream_model_path() == model_file


def test_moondream_provider_local_query(tmp_path):
    from PIL import Image

    image = tmp_path / "receipt.jpg"
    Image.new("RGB", (20, 20), "white").save(image)

    model_file = tmp_path / "moondream-0_5b-int8.mf"
    model_file.write_bytes(b"weights")

    fake_md = MagicMock()
    fake_model = MagicMock()
    fake_md.vl.return_value = fake_model
    fake_model.encode_image.return_value = "encoded"
    fake_model.query.return_value = {"answer": '{"ticket": {"date": "", "chaine_supermarche": "A", "adresse": "", "produits": []}}'}

    with patch.dict("sys.modules", {"moondream": fake_md}):
        with patch(
            "receipt_ocr.backends.vlm.moondream_provider.prepare_vlm_image",
            return_value=(str(image), []),
        ):
            provider = MoondreamProvider(model_path=model_file, max_image_side=0)
            answer = provider.analyze(str(image), "prompt")

    assert "ticket" in answer
    fake_model.query.assert_called_once()


def test_moondream_provider_missing_config_raises():
    with patch(
        "receipt_ocr.backends.vlm.moondream_provider.resolve_moondream_model_path",
        return_value=None,
    ):
        with patch.dict("sys.modules", {"moondream": MagicMock()}):
            with pytest.raises(OcrBackendError, match="local weights not found"):
                MoondreamProvider()


def test_moondream_provider_ignores_cloud_api_key(monkeypatch):
    monkeypatch.setenv("MOONDREAM_API_KEY", "fake-key-should-not-be-used")
    with patch(
        "receipt_ocr.backends.vlm.moondream_provider.resolve_moondream_model_path",
        return_value=None,
    ):
        with patch.dict("sys.modules", {"moondream": MagicMock()}):
            with pytest.raises(OcrBackendError, match="local weights not found"):
                MoondreamProvider()
