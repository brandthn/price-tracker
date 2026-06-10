"""Hybrid CLIP + SmolLM2 Vision-Language Model for French receipt parsing.

Training-side package. May import :mod:`receipt_ocr` (constants, image prep),
never the reverse — except the single runtime provider file which lazily
imports the model classes defined here.
"""

__version__ = "0.1.0"
