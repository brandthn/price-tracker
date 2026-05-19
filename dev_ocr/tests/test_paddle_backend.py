"""Tests for :class:`receipt_ocr.backends.paddle_backend.PaddleOcrBackend`.

PaddleOCR is heavy and may not be installed in CI, so we patch the
import + the engine. Two scenarios matter:

* PaddleOCR not installed → instantiation raises :class:`ImportError`.
* PaddleOCR installed → ``extract_text`` flattens the nested output
  and wraps engine failures in :class:`OcrBackendError`.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from receipt_ocr.exceptions import OcrBackendError


def _install_fake_paddleocr(monkeypatch, *, engine_factory) -> MagicMock:
    """Replace the (potentially missing) ``paddleocr`` module with a fake.

    ``engine_factory`` is called to obtain the object returned by
    ``PaddleOCR(...)`` so each test can craft its own engine behaviour.
    """
    fake_module = types.ModuleType("paddleocr")

    paddle_ocr_cls = MagicMock(name="PaddleOCR", side_effect=lambda **kw: engine_factory())
    fake_module.PaddleOCR = paddle_ocr_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    return paddle_ocr_cls


def test_paddle_backend_raises_import_error_when_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "paddleocr", None)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    with pytest.raises(ImportError):
        PaddleOcrBackend()


def test_paddle_backend_flattens_engine_output(tmp_path, monkeypatch):
    engine = MagicMock()
    engine.ocr.return_value = [
        [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], ("CARREFOUR", 0.99)],
            [[[0, 10], [10, 10], [10, 20], [0, 20]], ("PAIN 1,20", 0.95)],
        ]
    ]
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend(lang="fr")
    text = backend.extract_text(str(image))

    assert "CARREFOUR" in text
    assert "PAIN 1,20" in text
    assert text == "CARREFOUR\nPAIN 1,20"


def test_paddle_backend_validates_path_before_engine(monkeypatch, tmp_path):
    engine = MagicMock()
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    backend = PaddleOcrBackend()
    with pytest.raises(FileNotFoundError):
        backend.extract_text(str(tmp_path / "missing.jpg"))
    engine.ocr.assert_not_called()


def test_paddle_backend_wraps_engine_errors(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.ocr.side_effect = RuntimeError("CUDA exploded")
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend()
    with pytest.raises(OcrBackendError):
        backend.extract_text(str(image))


def test_paddle_backend_handles_empty_engine_output(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.ocr.return_value = [None]  # Paddle returns [None] on a blank page
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend()
    assert backend.extract_text(str(image)) == ""
