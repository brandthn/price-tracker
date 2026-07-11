"""Interface et orchestration Vision-Language Model pour :class:`VlmBackend`.

Pas de registre/factory ici (contrairement à ``dev_ocr``) : chaque worker
instancie son provider concret et le passe à ``VlmBackend(provider=...)``.
"""

from pricetracker_receipt_pipeline.backends.vlm.base import VlmProvider
from pricetracker_receipt_pipeline.backends.vlm.extraction import run_vlm_extraction

__all__ = ["VlmProvider", "run_vlm_extraction"]
