"""Abstract interface for Vision-Language Model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VlmProvider(ABC):
    """Strategy interface for multimodal models used by :class:`VlmBackend`."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Stable identifier (e.g. ``moondream-0.5b``)."""

    @abstractmethod
    def analyze(self, image_path: str, prompt: str) -> str:
        """Run the model on ``image_path`` with ``prompt`` and return raw text."""
