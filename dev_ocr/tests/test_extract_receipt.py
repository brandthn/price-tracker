"""Tests for the public entry point :func:`receipt_ocr.extract_receipt`.

Focuses on backend selection, env-variable handling and the
backend-swap guarantee of the Strategy pattern.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from receipt_ocr import extract_receipt
from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.constants import ENV_BACKEND, BackendName
from receipt_ocr.extract_receipt import build_backend, reset_default_backend
from tests.fixtures import sample_texts


@pytest.fixture(autouse=True)
def _clear_backend_cache():
    reset_default_backend()
    yield
    reset_default_backend()


class _FakeBackend(OcrBackend):
    """A tiny in-test backend that returns a hard-coded string."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[str] = []

    def extract_text(self, image_path: str) -> str:
        self.calls.append(image_path)
        return self._text


def test_extract_receipt_happy_path_with_explicit_backend():
    backend = _FakeBackend(sample_texts.HAPPY_PATH)

    result = extract_receipt("/tmp/whatever.jpg", backend=backend)

    assert backend.calls == ["/tmp/whatever.jpg"]
    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR MARKET"
    assert len(result["ticket"]["produits"]) >= 1


def test_extract_receipt_swapping_backends_returns_same_schema():
    backend_a = _FakeBackend(sample_texts.HAPPY_PATH)
    backend_b = _FakeBackend(sample_texts.WITH_QUANTITY)

    result_a = extract_receipt("a.jpg", backend=backend_a)
    result_b = extract_receipt("b.jpg", backend=backend_b)

    # Same schema for both — proves the Strategy pattern works.
    assert set(result_a["ticket"].keys()) == set(result_b["ticket"].keys())
    assert result_a["ticket"]["chaine_supermarche"] != result_b["ticket"]["chaine_supermarche"]


def test_extract_receipt_propagates_file_not_found(monkeypatch):
    """Wrong image path → FileNotFoundError (raised by the real backend)."""
    # Use the abstract path-validation helper directly via a tiny subclass
    # that calls it without depending on any OCR library.
    class _PathOnlyBackend(OcrBackend):
        def extract_text(self, image_path: str) -> str:
            self._validate_image_path(image_path)
            return "unreachable"

    with pytest.raises(FileNotFoundError):
        extract_receipt("/does/not/exist.jpg", backend=_PathOnlyBackend())


def test_build_backend_defaults_to_paddle_class(monkeypatch):
    monkeypatch.delenv(ENV_BACKEND, raising=False)
    with patch("receipt_ocr.extract_receipt._BACKEND_REGISTRY") as registry:
        sentinel = MagicMock()
        sentinel.return_value = MagicMock(spec=OcrBackend)
        registry.__getitem__.return_value = sentinel

        build_backend(force_new=True)

        registry.__getitem__.assert_called_once_with(BackendName.PADDLE)
        sentinel.assert_called_once_with()


def test_build_backend_reuses_cached_instance(monkeypatch):
    monkeypatch.delenv(ENV_BACKEND, raising=False)
    with patch("receipt_ocr.extract_receipt._BACKEND_REGISTRY") as registry:
        instance = MagicMock(spec=OcrBackend)
        sentinel = MagicMock(return_value=instance)
        registry.__getitem__.return_value = sentinel

        first = build_backend()
        second = build_backend()

        assert first is second
        sentinel.assert_called_once()


def test_build_backend_honours_env_variable(monkeypatch):
    monkeypatch.setenv(ENV_BACKEND, "tesseract")
    with patch("receipt_ocr.extract_receipt._BACKEND_REGISTRY") as registry:
        sentinel = MagicMock()
        sentinel.return_value = MagicMock(spec=OcrBackend)
        registry.__getitem__.return_value = sentinel

        build_backend()

        registry.__getitem__.assert_called_once_with(BackendName.TESSERACT)


def test_build_backend_explicit_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv(ENV_BACKEND, "tesseract")
    with patch("receipt_ocr.extract_receipt._BACKEND_REGISTRY") as registry:
        sentinel = MagicMock()
        sentinel.return_value = MagicMock(spec=OcrBackend)
        registry.__getitem__.return_value = sentinel

        build_backend("vlm")

        registry.__getitem__.assert_called_once_with(BackendName.VLM)


def test_build_backend_unknown_name_raises(monkeypatch):
    monkeypatch.delenv(ENV_BACKEND, raising=False)
    with pytest.raises(ValueError):
        build_backend("totally-made-up")


def test_stub_backends_raise_not_implemented():
    from receipt_ocr.backends import EasyOcrBackend, TesseractBackend

    for stub_cls in (TesseractBackend, EasyOcrBackend):
        with pytest.raises(NotImplementedError):
            stub_cls()


def test_vlm_backend_with_injected_provider(tmp_path):
    from receipt_ocr.backends.vlm_backend import VlmBackend
    from tests.fixtures import vlm_json

    class _Provider:
        model_id = "moondream-0.5b"

        def analyze(self, image_path: str, prompt: str) -> str:
            return vlm_json.VALID_VLM_JSON

    image = tmp_path / "x.jpg"
    image.write_bytes(b"x")
    backend = VlmBackend(provider=_Provider())
    result = extract_receipt(str(image), backend=backend)
    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR MARKET"
