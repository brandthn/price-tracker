"""Multi-pass VLM extraction — smaller focused prompts merged into one ticket."""

from __future__ import annotations

import json

from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.prompts import (
    MULTIPASS_DATE_PROMPT,
    MULTIPASS_HEADER_PROMPT,
    MULTIPASS_PRODUCTS_PROMPT,
)
from receipt_ocr.vlm_parse import merge_partial_tickets, try_parse_vlm_json


def run_multipass_extraction(provider: VlmProvider, image_path: str) -> str:
    """Run header / date / products passes and return merged JSON string."""
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
            from receipt_ocr.vlm_parse import loads_vlm_payload

            raw = loads_vlm_payload(answer)
            if isinstance(raw, dict):
                partials.append(raw)

    merged = merge_partial_tickets(partials)
    normalized = try_parse_vlm_json(json.dumps(merged, ensure_ascii=False))
    if normalized is None:
        return json.dumps(merged, ensure_ascii=False)
    return json.dumps(normalized, ensure_ascii=False)
