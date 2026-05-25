#!/usr/bin/env python3
"""Benchmark VLM modes on local receipt images."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_IMAGES = [
    ROOT / "data/raw/images_tickets_caisse/image_12.jpg",
    ROOT / "data/raw/images_tickets_caisse/image_2.jpg",
    ROOT / "data/raw/images_tickets_caisse/image_5.jpg",
]
MODES = ("transcribe", "json", "multipass")
OUT_DIR = ROOT / "data" / "benchmarks" / "vlm"


def main() -> int:
    from receipt_ocr import extract_receipt, reset_default_backend
    from receipt_ocr.backends.vlm_backend import VlmBackend
    from receipt_ocr.constants import VlmMode
    from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError

    images = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_IMAGES
    images = [p for p in images if p.is_file()]
    if not images:
        print("No images found.", file=sys.stderr)
        return 1

    os.environ.setdefault("RECEIPT_OCR_BACKEND", "vlm")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary: list[dict] = []

    for mode in MODES:
        os.environ["RECEIPT_VLM_MODE"] = mode
        reset_default_backend()
        backend = VlmBackend()
        for image in images:
            t0 = time.perf_counter()
            row = {
                "mode": mode,
                "image": image.name,
                "seconds": None,
                "products": 0,
                "chain": "",
                "error": "",
            }
            try:
                result = extract_receipt(str(image), backend=backend)
                row["seconds"] = round(time.perf_counter() - t0, 1)
                ticket = result.get("ticket", {})
                row["products"] = len(ticket.get("produits", []))
                row["chain"] = ticket.get("chaine_supermarche", "")
                out_file = OUT_DIR / f"{stamp}_{mode}_{image.stem}.json"
                out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            except (OcrBackendError, ReceiptParseError) as exc:
                row["seconds"] = round(time.perf_counter() - t0, 1)
                row["error"] = str(exc)
            summary.append(row)
            print(row)

    summary_path = OUT_DIR / f"{stamp}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSummary: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
