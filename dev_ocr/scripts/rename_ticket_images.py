#!/usr/bin/env python3
"""Renomme les images de tickets en image_1.ext, image_2.ext, etc.

Tri alphabétique du dossier, puis renommage, et un rename_manifest.json qui garde
la correspondance ancien -> nouveau. Les fichiers déjà nommés image_N.ext sont
sautés, donc le script est rejouable après avoir ajouté des photos.

    python scripts/rename_ticket_images.py --dry-run
    python scripts/rename_ticket_images.py --dir chemin/vers/mes/images
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
    """Renomme les images dans l'ordre alphabétique. Rend les paires ancien/nouveau."""
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
