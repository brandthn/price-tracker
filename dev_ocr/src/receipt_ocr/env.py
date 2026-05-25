"""Load project ``.env`` into ``os.environ`` (idempotent)."""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_env() -> None:
    """Load ``.env`` from the repository root if present."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path, override=False)
