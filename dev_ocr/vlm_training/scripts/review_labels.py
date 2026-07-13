"""Aide a relire les pseudo-labels du split de test.

    python scripts/review_labels.py --list test
    python scripts/review_labels.py --mark-reviewed image_8.jpg image_11.jpg
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.real_photos import (  # noqa: E402
    REVIEW_FILENAME,
    SPLITS_FILENAME,
    list_receipt_images,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", default="data/real_labels")
    parser.add_argument("--images", default="../data/raw/images_tickets_caisse")
    parser.add_argument("--list", choices=("train", "val", "test", "all"), help="affiche un split")
    parser.add_argument("--mark-reviewed", nargs="+", metavar="IMAGE.jpg")
    parser.add_argument(
        "--mark-all-test",
        action="store_true",
        help="passe tout le split de test a reviewed=true",
    )
    args = parser.parse_args()

    labels_dir = Path(args.labels)
    images_dir = Path(args.images)
    review_path = labels_dir / REVIEW_FILENAME
    splits_path = labels_dir / SPLITS_FILENAME

    review: dict = {}
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))

    if args.list:
        splits = json.loads(splits_path.read_text(encoding="utf-8"))
        names = splits.get(args.list, []) if args.list != "all" else sorted(
            p.name for p in list_receipt_images(images_dir)
        )
        print(f"Split {args.list!r} ({len(names)} images):\n")
        for name in names:
            flag = review.get(name, {}).get("reviewed", False)
            label = labels_dir / (Path(name).stem + ".json")
            status = "reviewed" if flag else "PENDING"
            exists = "ok" if label.exists() else "NO LABEL"
            print(f"  [{status:8}] {name:20} label={exists}")
            print(f"             image: {images_dir / name}")
            print(f"             json:  {label}")
        pending = [n for n in names if not review.get(n, {}).get("reviewed")]
        if pending and args.list == "test":
            print(f"\n{len(pending)} test image(s) still unreviewed — evaluate.py will skip them.")
        return

    if args.mark_reviewed:
        for name in args.mark_reviewed:
            review.setdefault(name, {})["reviewed"] = True
        review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Marked reviewed: {', '.join(args.mark_reviewed)}")
        return

    if args.mark_all_test:
        splits = json.loads(splits_path.read_text(encoding="utf-8"))
        for name in splits.get("test", []):
            review.setdefault(name, {})["reviewed"] = True
        review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Marked all {len(splits.get('test', []))} test images as reviewed.")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
