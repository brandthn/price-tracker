"""Pseudo-label real receipt photos with the Groq provider, for manual review.

For every image in ``--images``, runs the production Groq JSON extraction and
writes a canonical label file ``<stem>.json`` into ``--output``, plus:

- ``review_status.json``: per-image ``{"reviewed": false}`` flags — flip to
  ``true`` after manually checking a label (mandatory for the test split);
- ``splits.json``: frozen train/val/test partition (created once, never
  overwritten).

Requires ``GROQ_API_KEY`` and ``pip install -e ..`` (receipt_ocr).

Usage:
    python scripts/pseudo_label.py \
        --images ../data/raw/images_tickets_caisse --output data/real_labels
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.real_photos import (  # noqa: E402
    REVIEW_FILENAME,
    SPLITS_FILENAME,
    freeze_splits,
    list_receipt_images,
)
from receipt_vlm.data.schema import serialize_ticket, ticket_from_dict  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, help="directory of receipt photos")
    parser.add_argument("--output", required=True, help="labels output directory")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-label images that already have a label file")
    parser.add_argument("--test-fraction", type=float, default=0.3)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    args = parser.parse_args()

    # The Groq provider only supports JSON mode; force it for this run.
    os.environ["RECEIPT_VLM_MODE"] = "json"

    from receipt_ocr.env import load_project_env

    load_project_env()  # pick up GROQ_API_KEY / groq_key from dev_ocr/.env

    from receipt_ocr.backends.vlm.extraction import run_vlm_extraction
    from receipt_ocr.backends.vlm.groq_provider import GroqProvider
    from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError
    from receipt_ocr.vlm_parse import try_parse_vlm_json

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    review_path = output / REVIEW_FILENAME
    review: dict = (
        json.loads(review_path.read_text(encoding="utf-8"))
        if review_path.exists()
        else {}
    )

    provider = GroqProvider()
    images = list_receipt_images(args.images)
    print(f"Found {len(images)} images in {args.images}")

    n_done, n_failed = 0, 0
    for image_path in images:
        label_path = output / (image_path.stem + ".json")
        if label_path.exists() and not args.overwrite:
            continue
        try:
            raw = run_vlm_extraction(provider, str(image_path))
        except (OcrBackendError, ReceiptParseError) as exc:
            print(f"  FAILED {image_path.name}: {exc}")
            n_failed += 1
            continue

        parsed = try_parse_vlm_json(raw)
        if parsed is None:
            print(f"  FAILED {image_path.name}: unparseable output")
            n_failed += 1
            continue

        ticket = ticket_from_dict(parsed)
        label_path.write_text(serialize_ticket(ticket), encoding="utf-8")
        review.setdefault(image_path.name, {"reviewed": False})
        n_done += 1
        print(f"  OK {image_path.name}: {len(ticket.produits)} produits")

    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Labelled {n_done}, failed {n_failed}. Review flags: {review_path}")

    if not (output / SPLITS_FILENAME).exists():
        labelled = [p.name for p in images if (output / (p.stem + ".json")).exists()]
        splits = freeze_splits(
            labelled, output,
            test_fraction=args.test_fraction, val_fraction=args.val_fraction,
        )
        print(
            f"Frozen splits: {len(splits['train'])} train / "
            f"{len(splits['val'])} val / {len(splits['test'])} test"
        )
        print("NOW: manually review every label in the test split and set "
              f"\"reviewed\": true in {review_path.name}.")


if __name__ == "__main__":
    main()
