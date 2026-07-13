"""L'interface que doit remplir un provider VLM."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VlmProvider(ABC):
    """Un modèle multimodal, vu par VlmBackend."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifiant stable du modèle."""

    @abstractmethod
    def analyze(self, image_path: str, prompt: str) -> str:
        """Fait tourner le modèle sur l'image, et rend le texte brut."""
