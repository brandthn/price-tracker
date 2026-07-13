"""Les backends OCR, interchangeables.

Chacun vit dans son module et importe sa lib tierce paresseusement, pour qu'on
puisse importer receipt_ocr sans avoir PaddleOCR ni Moondream installés.
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
