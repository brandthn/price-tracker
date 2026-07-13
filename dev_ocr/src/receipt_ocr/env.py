"""Chargement du .env + lecture typée des variables d'env."""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_env() -> None:
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


def env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default
