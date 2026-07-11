"""Clean raw text returned by VLM transcription modes."""

from __future__ import annotations

import re

_CHAT_PREFIX = re.compile(
    r"^(?:note\s*:|the image shows|i think|here is|voici|il s'agit)",
    re.IGNORECASE,
)
_JSON_FENCE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_JSON_FENCE_END = re.compile(r"\n?```\s*$")


def clean_vlm_transcription(text: str) -> str:
    """Strip chatty prefixes, markdown fences, and empty lines."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = _JSON_FENCE.sub("", cleaned, count=1)
    cleaned = _JSON_FENCE_END.sub("", cleaned).strip()

    lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _CHAT_PREFIX.match(stripped):
            continue
        if stripped.lower().startswith("json"):
            continue
        lines.append(stripped)
    return "\n".join(lines)
