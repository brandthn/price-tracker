"""PriceTracker — pipeline OCR tickets partagé par les workers OCR par backend.

Copie figée de ``dev_ocr/src/receipt_ocr`` (parser + orchestration VLM), sans
le registre de backends : chaque worker câble exactement UN backend concret et
le passe à :class:`ReceiptParser`. Le sous-paquet :mod:`.worker` porte le
runtime commun des workers (auth OIDC, GCS, Pub/Sub, Cloud SQL, mapper, poids).
"""

from pricetracker_receipt_pipeline.exceptions import (
    OcrBackendError,
    ReceiptOcrError,
    ReceiptParseError,
)
from pricetracker_receipt_pipeline.parser import ReceiptParser

__all__ = [
    "OcrBackendError",
    "ReceiptOcrError",
    "ReceiptParseError",
    "ReceiptParser",
]
