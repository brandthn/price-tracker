"""Interface commune aux moteurs OCR.

Un backend rend le texte brut, point. Toute la structuration est le boulot
de ReceiptParser.

Deux règles pour les implémentations :
- importer la lib tierce DANS la classe (souvent dans __init__), sinon
  `import receipt_ocr` casse dès qu'une des libs n'est pas installée ;
- rattraper les erreurs tierces en OcrBackendError, pour que l'appelant
  n'ait à connaître que nos exceptions à nous.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pricetracker_receipt_pipeline.exceptions import OcrBackendError


class OcrBackend(ABC):
    @abstractmethod
    def extract_text(self, image_path: str) -> str:
        """Texte OCR de l'image, lignes séparées par des \\n."""

    @staticmethod
    def _validate_image_path(image_path: str) -> Path:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {image_path!r}")
        return path
