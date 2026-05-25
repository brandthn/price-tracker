"""Pluggable Vision-Language Model providers for :class:`VlmBackend`."""

from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.registry import build_vlm_provider

__all__ = ["VlmProvider", "build_vlm_provider"]
