"""Custom exceptions for the :mod:`receipt_ocr` package.

Keeping a dedicated hierarchy lets callers catch package errors broadly
(``except ReceiptOcrError``) or precisely (``except OcrBackendError``).
"""

from __future__ import annotations


class ReceiptOcrError(Exception):
    """Base class for every error raised by :mod:`receipt_ocr`."""


class OcrBackendError(ReceiptOcrError):
    """Raised when an OCR backend fails to extract text from an image.

    Wraps any third-party exception so that callers never have to know
    which backend was used.
    """


class ReceiptParseError(ReceiptOcrError):
    """Raised when raw OCR text cannot be parsed into a structured receipt."""
