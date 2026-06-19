"""Re-OCR tier-2 : second LLM Groq + prompt correctif (boucle de feedback 👎).

Quand l'utilisateur juge l'output OCR erroné, on relance l'analyse avec un
modèle Groq plus costaud ET un prompt qui inclut l'extraction précédente,
en demandant explicitement une ré-analyse soignée. On bypasse volontairement
``receipt_ocr.extract_receipt`` (prompt figé) pour pouvoir injecter le résultat
précédent — tout en réutilisant son ``GroqProvider`` (préparation image + appel
vision) et son schéma de sortie, de sorte que le mapper reste identique.

Architecture future : tier-1 = VLM maison, tier-2 = LLM. Pour l'instant les deux
tiers sont des LLM Groq (scout en tier-1, modèle + costaud en tier-2).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from receipt_ocr.backends.vlm.groq_provider import GroqProvider
from receipt_ocr.backends.vlm.prompts import RECEIPT_EXTRACTION_PROMPT
from receipt_ocr.constants import (
    ENV_GROQ_MODEL,
    ENV_VLM_MODE,
    VlmMode,
)
from receipt_ocr.exceptions import ReceiptOcrError

from .ocr import OcrProcessingError

# Bloc correctif ajouté au prompt d'extraction standard.
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


def build_corrective_prompt(previous_json: str) -> str:
    return RECEIPT_EXTRACTION_PROMPT + _CORRECTIVE_TEMPLATE.format(previous_json=previous_json)


def _parse_json_object(content: str) -> dict:
    """Parse la réponse du LLM en dict, avec réparation tolérante en fallback."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        import json_repair

        parsed = json_repair.loads(content)
    if not isinstance(parsed, dict):
        raise OcrProcessingError("Retry OCR did not return a JSON object.")
    return parsed


def run_retry_ocr(image_bytes: bytes, previous_json: str, model: str) -> dict:
    """Seconde passe OCR via Groq direct + prompt correctif. Retourne le dict brut.

    Le dict renvoyé a la même forme que ``receipt_ocr.extract_receipt``
    (``{"ticket": {...}}``) pour être consommé tel quel par le mapper.
    """
    # GroqProvider exige le mode JSON ; on force la sélection du modèle tier-2.
    os.environ[ENV_VLM_MODE] = VlmMode.JSON.value
    os.environ[ENV_GROQ_MODEL] = model

    prompt = build_corrective_prompt(previous_json)

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
