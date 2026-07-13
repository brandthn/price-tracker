#!/usr/bin/env python3
"""Passe un ticket dans Groq (mode JSON) et affiche le résultat.

Demande requirements-groq.txt installé et GROQ_API_KEY dans le .env. Sans argument,
prend la première image de data/raw/images_tickets_caisse/.

    python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/image_2.jpg
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from receipt_ocr.env import load_project_env

load_project_env()

from receipt_ocr import extract_receipt, reset_default_backend
from receipt_ocr.constants import ENV_VLM_MODE, ENV_VLM_MODEL, VlmModelName, VlmMode


def _resolve_image_path(raw: str) -> Path:
    """Résout le chemin depuis la racine du repo. Accepte un fichier ou un dossier."""
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if path.is_dir():
        return path
    if not path.is_file():
        raise FileNotFoundError(f"Receipt image not found: {path}")
    return path


def main() -> int:
    os.chdir(ROOT)

    parser = argparse.ArgumentParser(
        description="Extract one receipt via Groq vision (JSON mode).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "image",
        nargs="?",
        default=str(ROOT / "data" / "raw" / "images_tickets_caisse"),
        help="Chemin de l'image (défaut : la première de images_tickets_caisse/)",
    )
    args = parser.parse_args()

    try:
        image_path = _resolve_image_path(args.image)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    if image_path.is_dir():
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        candidates = sorted(
            p for p in image_path.iterdir() if p.suffix.lower() in exts
        )
        if not candidates:
            print(f"No images in {image_path}", file=sys.stderr)
            return 1
        image_path = candidates[0]

    os.environ["RECEIPT_OCR_BACKEND"] = "vlm"
    os.environ[ENV_VLM_MODEL] = VlmModelName.GROQ_LLAMA4_SCOUT.value
    os.environ[ENV_VLM_MODE] = VlmMode.JSON.value
    reset_default_backend()

    started = time.perf_counter()
    try:
        result = extract_receipt(str(image_path))
    except Exception as exc:
        print(f"Failed ({image_path}): {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nOK in {elapsed:.2f}s — {image_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
