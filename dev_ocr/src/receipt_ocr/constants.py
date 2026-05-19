"""Constants shared across the package.

Centralising the field names of the output schema avoids magic strings
in the parser and makes refactors straightforward.
"""

from __future__ import annotations

from enum import Enum


class TicketField(str, Enum):
    """Top-level keys of the output JSON schema."""

    TICKET = "ticket"
    DATE = "date"
    CHAINE = "chaine_supermarche"
    ADRESSE = "adresse"
    PRODUITS = "produits"


class ProductField(str, Enum):
    """Keys of a single product entry."""

    NOM = "nom_produit"
    PRIX = "prix_unitaire_ou_kg"
    UNITES = "unites"


OUTPUT_DATE_FORMAT = "%Y%m%d %H:%M"
"""Target date format: ``yyyyMMdd HH:mm``."""


class BackendName(str, Enum):
    """Identifiers accepted by the backend factory / env variable."""

    PADDLE = "paddle"
    TESSERACT = "tesseract"
    EASYOCR = "easyocr"
    VLM = "vlm"


ENV_BACKEND = "RECEIPT_OCR_BACKEND"
"""Name of the environment variable selecting the default backend."""
