"""OCR tier-2 : appel Groq vision direct + prompt correctif.

On bypasse ``receipt_ocr.extract_receipt`` (prompt figé) afin d'injecter
l'extraction précédente jugée erronée, tout en réutilisant son ``GroqProvider``
(préparation image + appel vision) et son schéma de sortie → le mapper reste
identique au worker tier-1.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from receipt_ocr.backends.vlm.groq_provider import GroqProvider
from receipt_ocr.backends.vlm.prompts import RECEIPT_EXTRACTION_PROMPT
from receipt_ocr.constants import ENV_GROQ_MODEL, ENV_VLM_MODE, VlmMode
from receipt_ocr.exceptions import ReceiptOcrError


class OcrProcessingError(Exception):
    """Wraps failures from the receipt_ocr package / Groq call."""


_CORRECTIVE_TEMPLATE = """\

ATTENTION — SECONDE ANALYSE.
Une première analyse automatique a produit l'extraction JSON ci-dessous, que \
l'utilisateur a signalée comme ERRONÉE :

{previous_json}

Ré-analyse l'image du ticket avec le plus grand soin. Corrige les erreurs \
(libellés de produits mal lus, prix, quantités, enseigne, date). Ne recopie pas \
aveuglément l'extraction précédente : vérifie chaque ligne sur l'image. Renvoie \
UNIQUEMENT le JSON corrigé, au même schéma que ci-dessus.
"""


def build_previous_extraction_json(
    enseigne: str | None,
    date_ticket: Any,
    prev_rows: list[dict[str, Any]],
) -> str:
    """Reconstruit l'extraction précédente au schéma receipt_ocr (JSON compact)."""
    produits = [
        {
            "nom_produit": row.get("raw_text") or "",
            "prix_unitaire_ou_kg": float(row["unit_price"]) if row.get("unit_price") is not None else 0.0,
            "unites": float(row["quantity"]) if row.get("quantity") is not None else 1,
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
    return RECEIPT_EXTRACTION_PROMPT + _CORRECTIVE_TEMPLATE.format(previous_json=previous_json)


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
    """Seconde passe OCR via Groq. Retourne le dict brut ``{"ticket": {...}}``."""
    # GroqProvider exige le mode JSON ; on force la sélection du modèle.
    os.environ[ENV_VLM_MODE] = VlmMode.JSON.value
    os.environ[ENV_GROQ_MODEL] = model

    prompt = build_prompt(previous_json)

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(image_bytes)
        tmp.flush()
        tmp.close()
        provider = GroqProvider(model=model)
        content = provider.analyze(str(tmp_path), prompt)
        return _parse_json_object(content)
    except ReceiptOcrError as exc:
        raise OcrProcessingError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
