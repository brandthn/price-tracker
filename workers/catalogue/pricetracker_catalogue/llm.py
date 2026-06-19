"""Matching ticket ↔ dataset via Gemini vision (Vertex AI).

Utilise `gemini-1.5-flash-002` — même auth ADC que le reste du projet
(pas de clé API externe, cohérence avec workers/off/vertex.py).

Lazy-load du SDK Vertex pour ne pas payer le coût d'import au boot.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from pathlib import Path

import requests

from .config import Settings
from .logging import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "matching_prompt.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Lazy-loaded
_vertex_model = None


def _get_model(settings: Settings):
    global _vertex_model
    if _vertex_model is not None:
        return _vertex_model

    import vertexai
    from vertexai.generative_models import GenerativeModel

    vertexai.init(
        project=settings.google_cloud_project or None,
        location=settings.prt_gcp_region,
    )
    _vertex_model = GenerativeModel(settings.prt_vertex_model)
    logger.info("vertex_model_loaded", model=settings.prt_vertex_model)
    return _vertex_model


# ─────────────────────────────────────────────────────────────────────────────
# TÉLÉCHARGEMENT IMAGE
# ─────────────────────────────────────────────────────────────────────────────

def download_image(proof_file_path: str, settings: Settings) -> bytes | None:
    url = settings.prt_off_image_base_url + proof_file_path
    try:
        r = requests.get(
            url,
            timeout=settings.prt_image_download_timeout,
            headers={"User-Agent": "PriceTrackerBot/1.0"},
        )
        r.raise_for_status()
        return r.content
    except requests.exceptions.Timeout:
        logger.warning("image_timeout", url=url)
        return None
    except Exception as e:
        logger.warning("image_download_error", url=url, error=str(e))
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FORMATAGE DU CONTEXTE
# ─────────────────────────────────────────────────────────────────────────────

def _format_candidats(produits: list[dict], enseigne: str, max_items: int) -> str:
    lines = [
        f"Enseigne : {enseigne}",
        f"Produits dans la base pour ce ticket ({min(len(produits), max_items)} produits) :",
    ]
    for i, p in enumerate(produits[:max_items], 1):
        prix_str = f"{p['prix']:.2f}€" if p["prix"] is not None else "prix inconnu"
        nom_str = p["nom_dataset"] or "nom non renseigné"
        lines.append(f"{i}. EAN: {p['ean']} | Prix: {prix_str} | Nom: {nom_str}")
    return "\n".join(lines)


def _detect_mime(proof_file_path: str) -> str:
    ext = proof_file_path.rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "png": "image/png"}.get(ext, "image/jpeg")


# ─────────────────────────────────────────────────────────────────────────────
# APPEL LLM
# ─────────────────────────────────────────────────────────────────────────────

def match_ticket(
    image_bytes: bytes,
    proof_file_path: str,
    produits_candidats: list[dict],
    enseigne: str,
    settings: Settings,
) -> dict:
    """
    Envoie l'image + candidats à Gemini. Retourne le JSON parsé du LLM.
    En cas d'erreur retourne {"erreur": "..."}.
    """
    from vertexai.generative_models import GenerationConfig, Image, Part

    model = _get_model(settings)
    contexte = _format_candidats(
        produits_candidats, enseigne, settings.prt_llm_max_candidats
    )

    image_part = Part.from_data(
        data=image_bytes,
        mime_type=_detect_mime(proof_file_path),
    )
    text_part = f"{_SYSTEM_PROMPT}\n\n{contexte}"

    try:
        response = model.generate_content(
            [image_part, text_part],
            generation_config=GenerationConfig(
                temperature=0.0,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        """response = model.generate_content(
            [image_part, text_part],
            generation_config=GenerationConfig(
                temperature=settings.prt_llm_temperature,
                max_output_tokens=settings.prt_llm_max_tokens,
                response_mime_type="application/json",
            ),
        )"""
        raw = response.text
        return json.loads(raw)

    except json.JSONDecodeError as e:
        logger.error("llm_json_error", error=str(e))
        return {"erreur": f"JSON invalide : {e}"}
    except Exception as e:
        logger.error("llm_call_error", error=str(e))
        return {"erreur": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# POST-TRAITEMENT
# ─────────────────────────────────────────────────────────────────────────────

def _normalise(texte: str) -> str:
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9 .]", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    m = re.search(r"[a-z]{3,}", texte)
    return texte[m.start():] if m else texte


def filter_reliable_matches(
    llm_result: dict,
    produits_candidats: list[dict],
    proof_id: int,
    enseigne: str,
    settings: Settings,
) -> list[dict]:
    """
    Filtre les matches LLM :
    - EAN doit exister dans les candidats (anti-hallucination)
    - confiance >= prt_confidence_threshold
    Retourne une liste prête pour pg.upsert_matches().
    """
    if "erreur" in llm_result:
        logger.warning("llm_error_skipped", proof_id=proof_id, detail=llm_result["erreur"])
        return []

    index = {p["ean"]: p for p in produits_candidats}
    eans_deja_utilises = set() 
    valides = []

    for match in llm_result.get("matches", []):
        ean = match.get("ean")
        confiance = match.get("confiance", 0)

        if not ean or ean not in index:
            continue
        if confiance < settings.prt_confidence_threshold:
            continue
        if ean in eans_deja_utilises:  
            logger.warning("llm_duplicate_ean", ean=ean, proof_id=proof_id)
            continue
        
        eans_deja_utilises.add(ean) 

        libelle = match.get("libelle_ticket", "")
        valides.append({
            "ean":               ean,
            "nom_canonique":     index[ean].get("nom_dataset") or "",
            "libelle_original":  libelle,
            "libelle_normalise": _normalise(libelle),
            "enseigne":          enseigne,
            "prix":              match.get("prix_ticket"),
            "proof_id":          proof_id,
        })

    return valides
