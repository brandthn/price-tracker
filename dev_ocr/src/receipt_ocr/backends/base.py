"""Abstract base class for every OCR backend.

A backend's only job is to take an image path and return the raw text
the OCR engine produced. All structuring/parsing is delegated to the
:class:`receipt_ocr.parser.ReceiptParser`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from receipt_ocr.exceptions import OcrBackendError


class OcrBackend(ABC):
    """Strategy interface for OCR engines.

    Concrete implementations must override :meth:`extract_text`.

    Implementation guidelines
    -------------------------
    * Import the third-party OCR library **inside the class** (typically
      in ``__init__``) so that ``import receipt_ocr`` works even when
      that library is not installed.
    * Convert any third-party error into :class:`OcrBackendError` so
      callers depend only on the package's own exception hierarchy.
    """

    @abstractmethod
    def extract_text(self, image_path: str) -> str:
        """Extract raw text from ``image_path``.

        Parameters
        ----------
        image_path:
            Filesystem path to the receipt image.

        Returns
        -------
        str
            The OCR'd text. Lines should be separated by ``\\n``.

        Raises
        ------
        OcrBackendError
            If the underlying OCR engine fails or the path is unusable.
        FileNotFoundError
            If ``image_path`` does not point to an existing file.
        """

    @staticmethod
    def _validate_image_path(image_path: str) -> Path:
        """Common path validation used by concrete backends.

        Returns the resolved :class:`Path` if it exists, otherwise
        raises :class:`FileNotFoundError`.
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {image_path!r}")
        return path
