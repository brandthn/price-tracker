"""Zippe les photos et leurs labels, pour les envoyer sur Drive.

Sert aux phases 2 et 3, qui ont besoin des vraies photos. La phase 1 n'en a pas besoin.

    python scripts/zip_colab_upload.py
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="colab_upload/receipt_vlm_colab_data.zip",
        help="output zip path",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]  # dev_ocr/
    images_dir = root / "data" / "raw" / "images_tickets_caisse"
    labels_dir = Path(__file__).resolve().parents[1] / "data" / "real_labels"

    if not images_dir.is_dir():
        raise SystemExit(f"Missing {images_dir}")
    if not labels_dir.is_dir():
        raise SystemExit(f"Missing {labels_dir} — run scripts/pseudo_label.py first.")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_img, n_json = 0, 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(images_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                arc = f"images_tickets_caisse/{path.name}"
                zf.write(path, arc)
                n_img += 1
        for path in sorted(labels_dir.glob("*.json")):
            zf.write(path, f"real_labels/{path.name}")
            n_json += 1

    size_mb = out.stat().st_size / 1e6
    print(f"Wrote {out} ({size_mb:.1f} MB): {n_img} images, {n_json} label files")
    print("A deposer dans My Drive/receipt_vlm/, le notebook le dezippe.")


if __name__ == "__main__":
    main()