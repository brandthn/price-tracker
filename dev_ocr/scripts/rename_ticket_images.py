#!/usr/bin/env python3
"""Rename receipt images to ``image_1.ext``, ``image_2.ext``, … (extensions unchanged).

Quick guide
-----------
**What it does:** Sorts images in a folder (A→Z), renames them ``image_1.jpg``,
``image_2.png``, etc., and writes ``rename_manifest.json`` (old → new names).

**Default folder:** ``data/raw/images_tickets_caisse/``

**Preview (no changes):** ``python scripts/rename_ticket_images.py --dry-run``

**Rename:** ``python scripts/rename_ticket_images.py``

**Custom folder:** ``python scripts/rename_ticket_images.py --dir path/to/my/images``

**Note:** Already-named ``image_N.ext`` files are skipped. Re-run after adding new
photos; check ``rename_manifest.json`` for the full mapping.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "raw" / "images_tickets_caisse"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def rename_ticket_images(
    directory: Path,
    *,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    """Rename images alphabetically to ``image_N<ext>``. Returns old→new names."""
    if not directory.is_dir():
        raise FileNotFoundError(directory)

    files = sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        raise RuntimeError(f"No images found in {directory}")

    mapping: list[tuple[Path, Path]] = []
    for index, source in enumerate(files, start=1):
        target = directory / f"image_{index}{source.suffix.lower()}"
        if source == target:
            continue
        mapping.append((source, target))

    # Two-phase rename via temp names to avoid collisions.
    temp_pairs: list[tuple[Path, Path]] = []
    for source, target in mapping:
        temp = directory / f"__rename_tmp_{source.name}"
        temp_pairs.append((source, temp))

    if dry_run:
        return [(s.name, t.name) for s, t in mapping]

    for source, temp in temp_pairs:
        source.rename(temp)
    for (_, temp), (_, target) in zip(temp_pairs, mapping):
        temp.rename(target)

    manifest = {old.name: new.name for old, new in mapping}
    manifest_path = directory / "rename_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return [(a, b) for a, b in manifest.items()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rename receipt images to image_1.ext, image_2.ext, …",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pairs = rename_ticket_images(args.dir, dry_run=args.dry_run)
    for old, new in pairs:
        print(f"{old} -> {new}")
    print(f"\n{len(pairs)} file(s)", end="")
    print(" (dry run)" if args.dry_run else " renamed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
