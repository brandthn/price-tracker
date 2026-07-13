"""Extraction en plusieurs passes : des prompts courts, puis on fusionne.

Un petit modèle répond bien mieux à trois questions étroites qu'à une seule question
large, d'où ce découpage en-tête / date / produits.
"""

from __future__ import annotations

import json

from pricetracker_receipt_pipeline.backends.vlm.base import VlmProvider
from pricetracker_receipt_pipeline.backends.vlm.prompts import (
    MULTIPASS_DATE_PROMPT,
    MULTIPASS_HEADER_PROMPT,
    MULTIPASS_PRODUCTS_PROMPT,
)
from pricetracker_receipt_pipeline.vlm_parse import merge_partial_tickets, try_parse_vlm_json


def run_multipass_extraction(provider: VlmProvider, image_path: str) -> str:
    """Enchaîne les trois passes, et rend le JSON fusionné."""
    prompts = (
        MULTIPASS_HEADER_PROMPT,
        MULTIPASS_DATE_PROMPT,
        MULTIPASS_PRODUCTS_PROMPT,
    )
    if hasattr(provider, "analyze_queries"):
        answers = provider.analyze_queries(image_path, list(prompts))  # type: ignore[attr-defined]
    else:
        answers = [provider.analyze(image_path, prompt) for prompt in prompts]

    partials: list[dict] = []
    for answer in answers:
        parsed = try_parse_vlm_json(answer)
        if parsed and "ticket" in parsed:
            partials.append(parsed["ticket"])
        else:
            from pricetracker_receipt_pipeline.vlm_parse import loads_vlm_payload

            raw = loads_vlm_payload(answer)
            if isinstance(raw, dict):
                partials.append(raw)

    merged = merge_partial_tickets(partials)
    normalized = try_parse_vlm_json(json.dumps(merged, ensure_ascii=False))
    if normalized is None:
        return json.dumps(merged, ensure_ascii=False)
    return json.dumps(normalized, ensure_ascii=False)
