#!/usr/bin/env python3
"""Smoke test: extract one receipt via Groq vision (JSON mode).

Runs ``extract_receipt`` with the Groq provider and prints the structured JSON
to stdout (README schema: ticket date, store, address, products).

Prerequisites
-------------
- ``pip install -r requirements-groq.txt``
- API key in ``.env`` at the repo root: ``GROQ_API_KEY`` or ``groq_key``
- From the repo root, set ``PYTHONPATH`` so the package imports

Usage — specific image path
---------------------------
Pass the full or relative path to one receipt image as the first argument.
The script prints the parsed JSON; progress and timing go to stderr.

PowerShell (repo root)::

    $env:PYTHONPATH = "src"
    python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg

bash::

    export PYTHONPATH=src
    python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg

Windows absolute path example::

    python scripts/test_groq_receipt.py "D:\\photos\\mon_ticket.jpg"

If you omit the argument, the script uses the first ``.jpg`` / ``.png`` / ``.webp``
file in ``data/raw/images_tickets_caisse/`` (or errors if that folder is empty).
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
    """Resolve ``raw`` against repo root; accept file or directory."""
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
        help="Receipt image path (default: first file in images_tickets_caisse/)",
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
