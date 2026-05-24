"""Tests for VLM registry and backend wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from receipt_ocr.backends.vlm.registry import build_vlm_provider
from receipt_ocr.backends.vlm_backend import VlmBackend
from receipt_ocr.constants import ENV_VLM_MODEL, VlmModelName
from receipt_ocr.exceptions import OcrBackendError
from tests.fixtures import vlm_json


class _FakeProvider:
    model_id = VlmModelName.MOONDREAM_0_5B.value

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def analyze(self, image_path: str, prompt: str) -> str:
        return vlm_json.VALID_VLM_JSON


def test_build_vlm_provider_default(monkeypatch):
    monkeypatch.delenv(ENV_VLM_MODEL, raising=False)
    with patch(
        "receipt_ocr.backends.vlm.moondream_provider.MoondreamProvider",
        _FakeProvider,
    ):
        provider = build_vlm_provider()
    assert provider.model_id == VlmModelName.MOONDREAM_0_5B.value


def test_build_vlm_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown VLM model"):
        build_vlm_provider("not-a-model")


def test_vlm_backend_delegates_to_provider(tmp_path):
    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake")

    provider = MagicMock()
    provider.model_id = "moondream-0.5b"
    provider.analyze.return_value = vlm_json.VALID_VLM_JSON

    backend = VlmBackend(provider=provider)
    text = backend.extract_text(str(image))

    provider.analyze.assert_called_once()
    assert "ticket" in text
    assert backend.active_model == "moondream-0.5b"


def test_vlm_backend_wraps_unexpected_errors(tmp_path):
    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake")

    provider = MagicMock()
    provider.model_id = "moondream-0.5b"
    provider.analyze.side_effect = RuntimeError("boom")

    backend = VlmBackend(provider=provider)
    with pytest.raises(OcrBackendError, match="VLM backend failed"):
        backend.extract_text(str(image))
