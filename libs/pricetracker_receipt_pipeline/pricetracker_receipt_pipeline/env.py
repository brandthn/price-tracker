"""Lecture typée des variables d'env.

Pas de chargement de .env ici : en prod la config vient de Cloud Run, pas
d'un fichier. C'est dev_ocr qui charge un .env, pas la lib.
"""

from __future__ import annotations

import os


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
