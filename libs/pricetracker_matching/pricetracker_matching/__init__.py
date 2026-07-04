"""PriceTracker matching — normaliseur + résolution EAN partagés par les workers OCR.

Lib dédiée (hors ``dev_ocr``/``receipt_ocr``, qui reste « OCR pur ») pour séparer
la logique métier de matching de l'extraction OCR, et pour éviter de toucher
``dev_ocr`` (dépôt travaillé en parallèle → conflits de merge).

>>> from pricetracker_matching import alias_lookup
>>> from pricetracker_matching.normalize import normalize_label
"""

from pricetracker_matching import alias_lookup, normalize
from pricetracker_matching.alias_lookup import ResolveStats, resolve_line_eans

__all__ = [
    "ResolveStats",
    "alias_lookup",
    "normalize",
    "resolve_line_eans",
]

__version__ = "0.1.0"
