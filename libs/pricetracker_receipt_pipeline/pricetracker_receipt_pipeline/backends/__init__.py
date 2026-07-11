"""OCR backends — pluggable via the Strategy pattern.

Seuls l'ABC :class:`OcrBackend` et le wrapper :class:`VlmBackend` vivent ici.
Les backends concrets (Paddle, Moondream, Groq, …) sont propres à chaque
worker : ils y sont copiés depuis ``dev_ocr`` et câblés en dur.
"""

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.backends.vlm_backend import VlmBackend

__all__ = ["OcrBackend", "VlmBackend"]
