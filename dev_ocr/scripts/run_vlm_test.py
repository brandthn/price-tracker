#!/usr/bin/env python3
"""Run VLM extract_receipt on one image and print JSON."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_IMAGE = ROOT / "data" / "raw" / "images_tickets_caisse" / "image_12.jpg"
DEFAULT_MODEL = ROOT / "data" / "models" / "moondream-0_5b-int8.mf"


def main() -> int:
    image = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE
    if not image.is_file():
        print(f"ERROR: image not found: {image}", file=sys.stderr)
        return 1

    model_path = Path(os.environ.get("RECEIPT_VLM_MODEL_PATH", DEFAULT_MODEL))
    if not model_path.is_file():
        print(f"ERROR: model weights not found: {model_path}", file=sys.stderr)
        print("Run: python scripts/download_moondream_weights.py", file=sys.stderr)
        return 1

    os.environ.setdefault("RECEIPT_VLM_MODEL_PATH", str(model_path))
    os.environ.setdefault("RECEIPT_VLM_MODE", "transcribe")
    os.environ["RECEIPT_OCR_BACKEND"] = "vlm"

    from receipt_ocr import extract_receipt, reset_default_backend
    from receipt_ocr.backends.vlm_backend import VlmBackend

    reset_default_backend()
    backend = VlmBackend()

    print(f"Image: {image}")
    print(f"Model: {model_path}")
    print(f"VLM:   {backend.active_model} (mode={backend.active_mode})")
    print("Running inference (first load may take a minute)...\n")

    t0 = time.perf_counter()
    try:
        result = extract_receipt(str(image), backend=backend)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0

    print(f"Done in {elapsed:.1f}s\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
