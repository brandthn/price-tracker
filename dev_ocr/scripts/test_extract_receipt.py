#!/usr/bin/env python3
"""Test the receipt_ocr public API: import and call extract_receipt().

This script exercises the module the same way an external app would:
import from ``receipt_ocr``, call ``extract_receipt(image_path)``, and
inspect the structured JSON result.

Usage (from the ``dev_ocr`` repo root)::

    python scripts/test_extract_receipt.py
    python scripts/test_extract_receipt.py path/to/ticket.jpg
    python scripts/test_extract_receipt.py --backend paddle

Environment (optional)::

    PYTHONPATH=src
    RECEIPT_OCR_BACKEND=ppocrv4|paddle|vlm
    RECEIPT_VLM_MODEL=moondream-0.5b
    RECEIPT_VLM_MODEL_PATH=/path/to/moondream-0_5b-int8.mf
    RECEIPT_VLM_MODEL_PATH=/path/to/moondream-0_5b-int8.mf  # required (local only)
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Make ``from receipt_ocr import extract_receipt`` work without pip install.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_IMAGE = ROOT / "data" / "raw" / "images_tickets_caisse" / "4PQOWWaPoa.jpg"


def _validate_schema(result: dict) -> list[str]:
    """Return a list of validation errors (empty = OK)."""
    errors: list[str] = []
    if "ticket" not in result:
        return ["Missing top-level key 'ticket'."]

    ticket = result["ticket"]
    required = ("date", "chaine_supermarche", "adresse", "produits")
    for key in required:
        if key not in ticket:
            errors.append(f"Missing ticket key '{key}'.")

    produits = ticket.get("produits")
    if not isinstance(produits, list):
        errors.append("'produits' must be a list.")
        return errors

    for i, product in enumerate(produits):
        for field in ("nom_produit", "prix_unitaire_ou_kg", "unites"):
            if field not in product:
                errors.append(f"produits[{i}] missing '{field}'.")
        if "prix_unitaire_ou_kg" in product and not isinstance(
            product["prix_unitaire_ou_kg"], (int, float)
        ):
            errors.append(f"produits[{i}].prix_unitaire_ou_kg must be numeric.")
        if "unites" in product and not isinstance(product["unites"], int):
            errors.append(f"produits[{i}].unites must be an integer.")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test receipt_ocr.extract_receipt on a receipt image.",
    )
    parser.add_argument(
        "image",
        nargs="?",
        default=str(DEFAULT_IMAGE),
        help=f"Receipt image path (default: {DEFAULT_IMAGE.name}).",
    )
    parser.add_argument(
        "--backend",
        choices=("paddle", "ppocrv4", "vlm"),
        default="ppocrv4",
        help="OCR backend (default: ppocrv4).",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"ERROR: image not found: {image_path}", file=sys.stderr)
        return 1

    # --- 1. Import the module (public API) ---------------------------------
    print("Step 1: Importing receipt_ocr …")
    try:
        from receipt_ocr import extract_receipt, reset_default_backend
        from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError
    except ImportError as exc:
        print(f"ERROR: cannot import receipt_ocr: {exc}", file=sys.stderr)
        print("Hint: run from dev_ocr/ with PYTHONPATH=src or pip install -e .", file=sys.stderr)
        return 1
    print("  OK — extract_receipt imported.")

    if args.backend:
        import os

        os.environ["RECEIPT_OCR_BACKEND"] = args.backend
        reset_default_backend()

    # --- 2. Call extract_receipt -------------------------------------------
    print(f"\nStep 2: Running extract_receipt on {image_path.name} …")
    print("  (first run loads OCR models — may take a minute)\n")

    t0 = time.perf_counter()
    try:
        result = extract_receipt(str(image_path))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OcrBackendError as exc:
        print(f"ERROR (OCR backend): {exc}", file=sys.stderr)
        return 1
    except ReceiptParseError as exc:
        print(f"ERROR (parser): {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0

    # --- 3. Validate and display -------------------------------------------
    print(f"Step 3: Done in {elapsed:.1f}s\n")

    errors = _validate_schema(result)
    if errors:
        print("Schema validation: FAILED")
        for err in errors:
            print(f"  - {err}")
    else:
        ticket = result["ticket"]
        n_products = len(ticket["produits"])
        print("Schema validation: OK")
        print(f"  date:              {ticket['date']!r}")
        print(f"  chaine_supermarche: {ticket['chaine_supermarche']!r}")
        print(f"  adresse:           {ticket['adresse']!r}")
        print(f"  produits:          {n_products} item(s)")

    print("\n--- Full JSON output ---\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
