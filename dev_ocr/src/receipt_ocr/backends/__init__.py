"""OCR backends — pluggable via the Strategy pattern.

Each backend lives in its own module and lazily imports its third-party
dependency, so :mod:`receipt_ocr` can be imported even if a particular
OCR library is not installed.
"""

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.easyocr_backend import EasyOcrBackend
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend
from receipt_ocr.backends.ppocr_v4_backend import PpOcrV4MobileBackend
from receipt_ocr.backends.tesseract_backend import TesseractBackend
from receipt_ocr.backends.vlm_backend import VlmBackend

__all__ = [
    "OcrBackend",
    "PaddleOcrBackend",
    "PpOcrV4MobileBackend",
    "TesseractBackend",
    "EasyOcrBackend",
    "VlmBackend",
]
