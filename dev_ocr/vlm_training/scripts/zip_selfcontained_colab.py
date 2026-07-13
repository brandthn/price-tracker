"""Met tout ce qu'il faut pour entrainer dans un seul zip : ni GitHub, ni Drive.

Le code (receipt_ocr et receipt_vlm), les scripts, les configs, les photos et leurs
labels. On depose le zip dans le notebook et on lance.

L'archive garde une racine dev_ocr/ pour que le notebook puisse faire un
`pip install -e dev_ocr` puis un `pip install -e dev_ocr/vlm_training`.

    python scripts/zip_selfcontained_colab.py
    python scripts/zip_selfcontained_colab.py --no-images   # code seul (phase 1)
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

# dev_ocr/ : deux niveaux au-dessus (dev_ocr/vlm_training/scripts/).
DEV_OCR = Path(__file__).resolve().parents[2]

# Ce qu'on copie tel quel, relativement a dev_ocr/. Les globs sont expanses.
CODE_INCLUDE = [
    "pyproject.toml",
    "README.md",
    "src/receipt_ocr/**/*.py",
    "vlm_training/pyproject.toml",
    "vlm_training/README.md",
    "vlm_training/requirements-training.txt",
    "vlm_training/receipt_vlm/**/*.py",
    "vlm_training/scripts/*.py",
    "vlm_training/configs/*.yaml",
    "vlm_training/data/real_labels/*.json",
]

IMAGE_DIR = "data/raw/images_tickets_caisse"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# Jamais embarque, meme si un glob les attrape.
EXCLUDE_PARTS = {".venv", "__pycache__", ".pytest_cache", ".git", "checkpoints", "logs"}


def _excluded(path: Path) -> bool:
    return any(part in EXCLUDE_PARTS for part in path.parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEV_OCR / "vlm_training" / "colab_upload" / "receipt_vlm_colab_bundle.zip"),
        help="output zip path",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="skip the real photos (phase 1 only; smaller, faster upload)",
    )
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_code = n_img = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for pattern in CODE_INCLUDE:
            matches = [DEV_OCR / pattern] if "*" not in pattern else sorted(DEV_OCR.glob(pattern))
            for path in matches:
                if not path.is_file() or _excluded(path):
                    continue
                zf.write(path, f"dev_ocr/{path.relative_to(DEV_OCR).as_posix()}")
                n_code += 1

        if not args.no_images:
            images_dir = DEV_OCR / IMAGE_DIR
            if not images_dir.is_dir():
                raise SystemExit(f"Missing {images_dir}")
            for path in sorted(images_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    zf.write(path, f"dev_ocr/{IMAGE_DIR}/{path.name}")
                    n_img += 1

    size_mb = out.stat().st_size / 1e6
    print(f"Wrote {out} ({size_mb:.1f} MB)")
    print(f"  code files: {n_code}")
    print(f"  images:     {n_img}{' (skipped)' if args.no_images else ''}")
    print("\nA deposer dans le notebook train_receipt_vlm_selfcontained.ipynb.")


if __name__ == "__main__":
    main()
