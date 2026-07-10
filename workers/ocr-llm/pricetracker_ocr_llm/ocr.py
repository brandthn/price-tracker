"""OCR tier-2 : appel Vertex AI Gemini + prompt correctif Carrefour.

On appelle Gemini en vision directe (bypass de ``receipt_ocr.extract_receipt``),
avec un prompt local qui désambiguïse les colonnes du ticket (code TVA vs
quantité, montant payé de la ligne) et qui injecte l'extraction précédente jugée
erronée.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .config import get_settings
from .gemini_provider import GeminiProvider
from .prompts import CORRECTIVE_TEMPLATE, RECEIPT_EXTRACTION_PROMPT


class OcrProcessingError(Exception):
    """Wraps failures from the OCR provider / JSON parsing."""


def build_previous_extraction_json(
    enseigne: str | None,
    date_ticket: Any,
    prev_rows: list[dict[str, Any]],
) -> str:
    """Reconstruit l'extraction précédente au schéma courant (JSON compact)."""
    produits = [
        {
            "nom_produit": row.get("raw_text") or "",
            "quantite": float(row["quantity"]) if row.get("quantity") is not None else 1,
            "prix_unitaire": float(row["unit_price"]) if row.get("unit_price") is not None else 0.0,
            "montant_ttc": float(row["line_total"]) if row.get("line_total") is not None else 0.0,
        }
        for row in prev_rows
    ]
    payload = {
        "ticket": {
            "date": str(date_ticket) if date_ticket else "",
            "chaine_supermarche": enseigne or "",
            "produits": produits,
        }
    }
    return json.dumps(payload, ensure_ascii=False)


def build_prompt(previous_json: str | None) -> str:
    """Prompt d'extraction de base, enrichi du bloc correctif si dispo."""
    if not previous_json:
        return RECEIPT_EXTRACTION_PROMPT
    return RECEIPT_EXTRACTION_PROMPT + CORRECTIVE_TEMPLATE.format(previous_json=previous_json)


def _parse_json_object(content: str) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        import json_repair

        parsed = json_repair.loads(content)
    if not isinstance(parsed, dict):
        raise OcrProcessingError("OCR did not return a JSON object.")
    return parsed


def run_ocr(image_bytes: bytes, model: str, previous_json: str | None = None) -> dict:
    """Seconde passe OCR via Gemini. Retourne le dict brut ``{"ticket": {...}}``."""
    settings = get_settings()
    prompt = build_prompt(previous_json)

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(image_bytes)
        tmp.flush()
        tmp.close()
        provider = GeminiProvider(
            model=model,
            project=settings.google_cloud_project,
            location=settings.prt_vertex_location,
        )
        content = provider.analyze(str(tmp_path), prompt)
        return _parse_json_object(content)
    finally:
        tmp_path.unlink(missing_ok=True)
