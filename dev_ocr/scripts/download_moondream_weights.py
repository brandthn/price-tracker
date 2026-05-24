#!/usr/bin/env python3
"""Download Moondream 0.5B int8 weights into data/models/ (gitignored).

Usage (from dev_ocr/)::

    python scripts/download_moondream_weights.py
    python scripts/download_moondream_weights.py --decompress-only
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "data" / "models"
GZ_NAME = "moondream-0_5b-int8.mf.gz"
MF_NAME = "moondream-0_5b-int8.mf"
HF_URL = (
    "https://huggingface.co/vikhyatk/moondream2/resolve/"
    "9dddae84d54db4ac56fe37817aeaeb502ed083e2/moondream-0_5b-int8.mf.gz"
)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    print(f"  -> {dest}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310 — fixed HF URL


def _decompress(gz_path: Path, mf_path: Path) -> None:
    print(f"Decompressing {gz_path.name} -> {mf_path.name}")
    with gzip.open(gz_path, "rb") as src, mf_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decompress-only",
        action="store_true",
        help="Only decompress an existing .mf.gz in data/models/.",
    )
    parser.add_argument(
        "--keep-gz",
        action="store_true",
        help="Keep the .mf.gz after decompressing.",
    )
    args = parser.parse_args()

    mf_path = MODELS_DIR / MF_NAME
    gz_path = MODELS_DIR / GZ_NAME

    if mf_path.is_file():
        print(f"Already present: {mf_path}")
        print(f"Set RECEIPT_VLM_MODEL_PATH={mf_path}")
        return 0

    if not args.decompress_only:
        if not gz_path.is_file():
            try:
                _download(HF_URL, gz_path)
            except OSError as exc:
                print(f"ERROR: download failed: {exc}", file=sys.stderr)
                return 1
        else:
            print(f"Using existing archive: {gz_path}")

    if not gz_path.is_file():
        print(f"ERROR: missing {gz_path}", file=sys.stderr)
        return 1

    try:
        _decompress(gz_path, mf_path)
    except OSError as exc:
        print(f"ERROR: decompress failed: {exc}", file=sys.stderr)
        return 1

    if not args.keep_gz:
        gz_path.unlink(missing_ok=True)

    print(f"\nReady: {mf_path}")
    print(f"export RECEIPT_VLM_MODEL_PATH={mf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
