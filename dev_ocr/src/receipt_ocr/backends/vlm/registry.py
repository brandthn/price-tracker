"""Factory for :class:`VlmProvider` implementations."""

from __future__ import annotations

import os
from typing import Any

from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.constants import DEFAULT_VLM_MODEL, ENV_VLM_MODEL, VlmModelName


def build_vlm_provider(
    name: str | None = None,
    **kwargs: Any,
) -> VlmProvider:
    """Instantiate a :class:`VlmProvider` by registry id.

    Resolution order for ``name``:

    1. Explicit ``name`` argument.
    2. ``RECEIPT_VLM_MODEL`` environment variable.
    3. :data:`DEFAULT_VLM_MODEL`.
    """
    resolved = (name or os.environ.get(ENV_VLM_MODEL) or DEFAULT_VLM_MODEL).strip().lower()
    if resolved == VlmModelName.MOONDREAM_0_5B.value:
        from receipt_ocr.backends.vlm.moondream_provider import MoondreamProvider

        return MoondreamProvider(**kwargs)

    valid = ", ".join(v.value for v in VlmModelName)
    raise ValueError(f"Unknown VLM model {resolved!r}. Valid options: {valid}.")
