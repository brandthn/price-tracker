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
    image = tmp_path / "receipt.jpg"
    image.write_bytes(b"fake-image")

    model_file = tmp_path / "moondream-0_5b-int8.mf"
    model_file.write_bytes(b"weights")

    fake_md = MagicMock()
    fake_model = MagicMock()
    fake_md.vl.return_value = fake_model
    fake_model.encode_image.return_value = "encoded"
    fake_model.query.return_value = {"answer": '{"ticket": {"date": "", "chaine_supermarche": "A", "adresse": "", "produits": []}}'}

    fake_pil_module = MagicMock()
    fake_image = MagicMock()
    fake_image.convert.return_value = fake_image
    fake_pil_module.Image.open.return_value.__enter__.return_value = fake_image

    with patch.dict("sys.modules", {"moondream": fake_md}):
        with patch(
            "receipt_ocr.backends.vlm.moondream_provider.Image",
            fake_pil_module.Image,
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
            with pytest.raises(OcrBackendError, match="Moondream is not configured"):
                MoondreamProvider(api_key=None)
