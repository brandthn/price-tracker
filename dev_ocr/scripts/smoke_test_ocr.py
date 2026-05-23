"""Quick smoke test: OCR one receipt image and print structured output.

Safe defaults (mobile models, image resize, 2 CPU threads) are applied
automatically by :class:`PaddleOcrBackend`.

Usage (from repo root)::

    python scripts/smoke_test_ocr.py
    python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg

Environment variables (optional)::

    RECEIPT_OCR_MAX_IMAGE_SIDE=1920
    RECEIPT_OCR_CPU_THREADS=2
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_IMAGE = ROOT / "data" / "raw" / "images_tickets_caisse" / "4PQOWWaPoa.jpg"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        nargs="?",
        default=str(DEFAULT_IMAGE),
        help=f"Path to a receipt image (default: {DEFAULT_IMAGE.name}).",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Print raw OCR text only (skip structured parsing).",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"Error: image not found: {image_path}", file=sys.stderr)
        return 1

    from receipt_ocr.backends.paddle_backend import PaddleOcrBackend
    from receipt_ocr import extract_receipt

    print(f"Image: {image_path}")
    print("Loading PaddleOCR (first run downloads models — may take a minute)...")
    t0 = time.perf_counter()
    backend = PaddleOcrBackend()
    print(f"  Init: {time.perf_counter() - t0:.1f}s")

    if args.raw_only:
        t1 = time.perf_counter()
        text = backend.extract_text(str(image_path))
        print(f"  OCR:  {time.perf_counter() - t1:.1f}s")
        print("\n--- Raw OCR text ---\n")
        print(text)
        return 0

    t1 = time.perf_counter()
    result = extract_receipt(str(image_path), backend=backend)
    print(f"  OCR+parse: {time.perf_counter() - t1:.1f}s")
    print("\n--- Structured output ---\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
