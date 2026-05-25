"""Tests for :class:`receipt_ocr.backends.ppocr_v4_backend.PpOcrV4MobileBackend`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from receipt_ocr.exceptions import OcrBackendError


def test_ppocr_v4_uses_first_successful_profile():
    mock_inner = MagicMock()
    mock_inner.extract_text.return_value = "LINE"

    with patch(
        "receipt_ocr.backends.ppocr_v4_backend.PaddleOcrBackend",
        side_effect=[OcrBackendError("static failed"), mock_inner],
    ) as paddle_cls:
        from receipt_ocr.backends.ppocr_v4_backend import PpOcrV4MobileBackend

        backend = PpOcrV4MobileBackend()
        assert backend.active_profile == "ppocrv4-dynamic-fallback"
        assert paddle_cls.call_count == 2
        assert backend.extract_text("img.jpg") == "LINE"


def test_ppocr_v4_raises_when_all_profiles_fail():
    with patch(
        "receipt_ocr.backends.ppocr_v4_backend.PaddleOcrBackend",
        side_effect=OcrBackendError("nope"),
    ):
        from receipt_ocr.backends.ppocr_v4_backend import PpOcrV4MobileBackend

        with pytest.raises(OcrBackendError, match="Failed to initialise PpOcrV4"):
            PpOcrV4MobileBackend()


def test_build_backend_ppocrv4_name():
    from receipt_ocr.extract_receipt import build_backend, reset_default_backend
    from receipt_ocr.constants import BackendName

    reset_default_backend()
    with patch(
        "receipt_ocr.extract_receipt._BACKEND_REGISTRY",
        {BackendName.PPOCRV4: MagicMock(return_value=MagicMock())},
    ):
        backend = build_backend("ppocrv4", force_new=True)
        assert backend is not None
