#!/usr/bin/env python3
"""Smoke test: extract one receipt via Groq vision (JSON mode)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from receipt_ocr import extract_receipt, reset_default_backend
from receipt_ocr.constants import ENV_VLM_MODE, ENV_VLM_MODEL, VlmModelName, VlmMode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        nargs="?",
        default=str(ROOT / "data" / "raw" / "images_tickets_caisse"),
        help="Receipt image path (default: first file in images_tickets_caisse/)",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
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
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nOK in {elapsed:.2f}s — {image_path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
