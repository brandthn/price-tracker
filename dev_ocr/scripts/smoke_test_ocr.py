"""Quick smoke test: OCR one receipt image and print structured output.

Usage (from repo root)::

    python scripts/smoke_test_ocr.py
    python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/image_2.jpg
    python scripts/smoke_test_ocr.py --backend ppocrv4

Environment variables (optional)::

    RECEIPT_OCR_MAX_IMAGE_SIDE=1280
    RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE=640
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

DEFAULT_IMAGE = ROOT / "data" / "raw" / "images_tickets_caisse" / "image_2.jpg"


def _create_backend(name: str):
    if name == "ppocrv4":
        from receipt_ocr.backends.ppocr_v4_backend import PpOcrV4MobileBackend

        return PpOcrV4MobileBackend()
    if name == "paddle":
        from receipt_ocr.backends.paddle_backend import PaddleOcrBackend

        return PaddleOcrBackend()
    if name == "vlm":
        from receipt_ocr.backends.vlm_backend import VlmBackend

        return VlmBackend()
    raise ValueError(f"Unknown backend {name!r}. Use 'paddle', 'ppocrv4', or 'vlm'.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        nargs="?",
        default=str(DEFAULT_IMAGE),
        help=f"Path to a receipt image (default: {DEFAULT_IMAGE.name}).",
    )
    parser.add_argument(
        "--backend",
        choices=("paddle", "ppocrv4", "vlm"),
        default="ppocrv4",
        help="OCR backend to use (default: ppocrv4).",
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

    from receipt_ocr import extract_receipt

    print(f"Image: {image_path}")
    print(f"Backend: {args.backend}")
    print("Loading OCR engine (first run may download models)...")
    t0 = time.perf_counter()
    try:
        backend = _create_backend(args.backend)
    except Exception as exc:
        print(f"Error: failed to load backend: {exc}", file=sys.stderr)
        return 1
    print(f"  Init: {time.perf_counter() - t0:.1f}s")

    if hasattr(backend, "active_profile"):
        print(f"  Profile: {backend.active_profile}")
        print(f"  Max image side: {backend.max_image_side}px")
        print(f"  Det model: {backend.det_model}")
        failed = getattr(backend, "failed_profiles", None)
        if failed:
            print(f"  Skipped profiles: {failed}")

    if args.raw_only:
        t1 = time.perf_counter()
        text = backend.extract_text(str(image_path))
        print(f"  OCR:  {time.perf_counter() - t1:.1f}s")
        print("\n--- Raw OCR text ---\n")
        print(text)
        return 0

    t1 = time.perf_counter()
    result = extract_receipt(str(image_path), backend=backend)
    elapsed = time.perf_counter() - t1
    print(f"  OCR+parse: {elapsed:.1f}s")
    if elapsed > 3.0:
        print("  Note: target for mobile CPU is <3s; desktop Python may be slower.")
    print("\n--- Structured output ---\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
