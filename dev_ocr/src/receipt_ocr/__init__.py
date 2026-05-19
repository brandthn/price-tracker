"""receipt_ocr — extract structured data from photos of French supermarket receipts.

Public API
----------
>>> from receipt_ocr import extract_receipt
>>> data = extract_receipt("path/to/ticket.jpg")
"""

from receipt_ocr.exceptions import (
    OcrBackendError,
    ReceiptOcrError,
    ReceiptParseError,
)
from receipt_ocr.extract_receipt import extract_receipt
from receipt_ocr.parser import ReceiptParser

__all__ = [
    "extract_receipt",
    "ReceiptParser",
    "OcrBackendError",
    "ReceiptParseError",
    "ReceiptOcrError",
]

__version__ = "0.1.0"
