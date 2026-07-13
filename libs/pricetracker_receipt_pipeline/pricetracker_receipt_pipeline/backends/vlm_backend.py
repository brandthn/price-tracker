"""Le backend VLM : il délègue tout à un provider.

Adapté de ``dev_ocr`` : le provider est un argument OBLIGATOIRE du
constructeur (pas de registre/factory — chaque worker câble le sien).
"""

from __future__ import annotations

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.backends.vlm.base import VlmProvider
from pricetracker_receipt_pipeline.backends.vlm.extraction import (
    load_vlm_mode,
    run_vlm_extraction,
)
from pricetracker_receipt_pipeline.exceptions import OcrBackendError, ReceiptParseError


class VlmBackend(OcrBackend):
    """Extrait un ticket via le provider VLM qu'on lui passe.

    Modes (``RECEIPT_VLM_MODE``): ``transcribe`` | ``json`` | ``multipass``.
    """

    def __init__(self, provider: VlmProvider) -> None:
        if not isinstance(provider, VlmProvider):
            raise TypeError(
                f"provider must be a VlmProvider instance, got {type(provider).__name__}"
            )
        self._provider = provider

    @property
    def active_model(self) -> str:
        return self._provider.model_id

    @property
    def active_mode(self) -> str:
        return load_vlm_mode()

    def extract_text(self, image_path: str) -> str:
        """Lance l'extraction VLM, et rend le texte que ReceiptParser va manger."""
        try:
            return run_vlm_extraction(self._provider, image_path)
        except (OcrBackendError, ReceiptParseError):
            raise
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"VLM backend failed on {image_path!r}: {exc}"
            ) from exc
