"""Exceptions du package."""

from __future__ import annotations


class ReceiptOcrError(Exception):
    pass


class OcrBackendError(ReceiptOcrError):
    """Le moteur OCR a échoué. Emballe l'exception tierce d'origine."""


class ReceiptParseError(ReceiptOcrError):
    """Texte OCR illisible : rien de structuré à en tirer."""
