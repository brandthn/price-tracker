"""Tests for :class:`receipt_ocr.backends.paddle_backend.PaddleOcrBackend`.

PaddleOCR is heavy and may not be installed in CI, so we patch the
``paddleocr`` entry in ``sys.modules`` at instantiation time.

Because ``PaddleOcrBackend`` imports ``paddleocr`` lazily *inside*
``__init__``, patching ``sys.modules`` before calling the constructor is
sufficient — no module-level reimport is needed.

Three scenarios are exercised:

* PaddleOCR not installed → instantiation raises :class:`ImportError`.
* PaddleOCR installed → ``extract_text`` flattens the v3 output format
  (``OCRResult``-like dict with ``rec_texts`` / ``rec_scores``).
* Engine / inference failures are wrapped in :class:`OcrBackendError`.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from receipt_ocr.exceptions import OcrBackendError


def _make_ocr_result(
    texts: list[str],
    scores: list[float] | None = None,
) -> dict:
    """Build a minimal ``OCRResult``-like dict matching PaddleOCR 3.x output."""
    return {
        "rec_texts": texts,
        "rec_scores": scores if scores is not None else [1.0] * len(texts),
    }


def _install_fake_paddleocr(monkeypatch, *, engine_factory) -> MagicMock:
    """Replace (or create) the ``paddleocr`` module with a thin fake.

    ``engine_factory`` is called for every ``PaddleOCR(...)`` call so that
    each test can control what the engine returns.
    """
    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = MagicMock(  # type: ignore[attr-defined]
        name="PaddleOCR",
        side_effect=lambda **kw: engine_factory(),
    )
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    return fake_module.PaddleOCR


def test_paddle_backend_raises_import_error_when_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "paddleocr", None)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    with pytest.raises(ImportError):
        PaddleOcrBackend()


def test_paddle_backend_flattens_engine_output(tmp_path, monkeypatch):
    engine = MagicMock()
    engine.predict.return_value = [
        _make_ocr_result(["CARREFOUR", "PAIN 1,20"], [0.99, 0.95]),
    ]
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend(lang="fr")
    text = backend.extract_text(str(image))

    assert text == "CARREFOUR\nPAIN 1,20"


def test_paddle_backend_filters_low_confidence(tmp_path, monkeypatch):
    engine = MagicMock()
    engine.predict.return_value = [
        _make_ocr_result(["GOOD TEXT", "junk"], [0.95, 0.10]),
    ]
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend(score_threshold=0.5)
    text = backend.extract_text(str(image))

    assert "GOOD TEXT" in text
    assert "junk" not in text


def test_paddle_backend_validates_path_before_engine(monkeypatch, tmp_path):
    engine = MagicMock()
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    backend = PaddleOcrBackend()
    with pytest.raises(FileNotFoundError):
        backend.extract_text(str(tmp_path / "missing.jpg"))
    engine.predict.assert_not_called()


def test_paddle_backend_wraps_engine_errors(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.predict.side_effect = RuntimeError("CUDA exploded")
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend()
    with pytest.raises(OcrBackendError):
        backend.extract_text(str(image))


def test_paddle_backend_handles_none_page_in_results(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = [None]
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend()
    assert backend.extract_text(str(image)) == ""


def test_paddle_backend_handles_empty_results(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = []
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "ticket.jpg"
    image.write_bytes(b"fake bytes")

    backend = PaddleOcrBackend()
    assert backend.extract_text(str(image)) == ""


def test_paddle_backend_defaults_to_paddle_dynamic_engine(monkeypatch):
    captured: list[dict] = []

    def _factory(**kw):
        captured.append(kw)
        return MagicMock()

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = MagicMock(side_effect=_factory)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    PaddleOcrBackend()
    assert captured[0].get("engine") == "paddle_dynamic"
    assert captured[0].get("enable_mkldnn") is False
    assert "text_detection_model_name" not in captured[0]


def test_paddle_backend_mobile_models_use_static_engine(monkeypatch):
    captured: list[dict] = []

    def _factory(**kw):
        captured.append(kw)
        return MagicMock()

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = MagicMock(side_effect=_factory)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend
    from receipt_ocr.constants import PADDLE_MOBILE_DET_MODEL

    PaddleOcrBackend(use_mobile_models=True)
    assert captured[0].get("engine") == "paddle_static"
    assert captured[0].get("text_detection_model_name") == PADDLE_MOBILE_DET_MODEL


def test_paddle_backend_resizes_large_images(tmp_path, monkeypatch):
    engine = MagicMock()
    engine.predict.return_value = [_make_ocr_result(["OK"], [0.99])]
    _install_fake_paddleocr(monkeypatch, engine_factory=lambda: engine)

    from PIL import Image

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

    image = tmp_path / "large.jpg"
    Image.new("RGB", (4000, 3000), color="white").save(image, "JPEG")

    backend = PaddleOcrBackend(max_image_side=800)
    backend.extract_text(str(image))

    called_path = engine.predict.call_args[0][0]
    assert called_path != str(image)
    assert called_path.endswith(".jpg")
