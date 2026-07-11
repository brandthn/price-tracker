"""Generate synthetic receipts with perfect canonical labels — parameterised & multilingual.

Dial the corpus up gradually and reproducibly: how many, which Latin-script languages, which
capture variations, how hard. Writes ``receipt_{i:06d}.png`` + canonical ``.json`` labels, plus a
``manifest.json`` recording the exact config (reproducible / auditable). Images round-robin across
the requested languages so they stay balanced.

Backward-compatible with the original French-only flags (``--n``, ``--output``, ``--diverse``,
``--distort``, ``--distort-intensity``, ``--start-index``).

Examples:
    # legacy French set (unchanged):
    python scripts/generate_synthetic.py --n 5000 --output data/synthetic --diverse --distort

    # 200 receipts across 3 languages, all variations, medium:
    python scripts/generate_synthetic.py --count 200 --languages fr,en,es --diverse --distort \\
        --out data/synth_demo

    # scale up with a chosen variation subset + extra fonts (biggest OCR-diversity lever):
    python scripts/generate_synthetic.py --count 10000 --languages fr,en,es,de,it --diverse \\
        --distort --variations warp,blur,chroma,jpeg,frame --intensity heavy \\
        --fonts-dir /path/to/ttfs --out data/synth_10k
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data import synthetic  # noqa: E402
from receipt_vlm.data.locales import available_locales  # noqa: E402
from receipt_vlm.data.schema import serialize_ticket  # noqa: E402
from receipt_vlm.data.synthetic import (  # noqa: E402
    ALL_VARIATIONS,
    generate_ticket,
    render_receipt_image,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", "--count", dest="count", type=int, default=2000,
                        help="number of receipts")
    parser.add_argument("--output", "--out", dest="output", default="data/synthetic",
                        help="output directory")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--languages", "--langs", dest="languages", default="fr",
                        help=f"comma list of Latin-script locales. Available: {','.join(available_locales())}")
    parser.add_argument("--diverse", action="store_true",
                        help="multi-style layouts, colour palettes, pre-render printer noise")
    parser.add_argument("--distort", action="store_true",
                        help="post-render capture distortions (see --variations)")
    parser.add_argument("--distort-intensity", "--intensity", dest="intensity",
                        choices=("light", "medium", "heavy"), default="medium")
    parser.add_argument("--variations", default="all",
                        help=f"'all', 'none', or comma subset of: {','.join(ALL_VARIATIONS)}")
    parser.add_argument("--fonts-dir", default=None,
                        help="extra .ttf/.otf pool for glyph diversity")
    parser.add_argument("--start-index", type=int, default=0,
                        help="first receipt index in filenames (append to an existing folder)")
    args = parser.parse_args()

    langs = [c.strip().lower() for c in args.languages.split(",") if c.strip()] or ["fr"]
    bad = [c for c in langs if c not in set(available_locales())]
    if bad:
        parser.error(f"unknown locale(s) {bad}; available: {','.join(available_locales())}")

    v = args.variations.strip().lower()
    if v == "all":
        variations: set[str] | None = None
    elif v == "none":
        variations = set()
    else:
        variations = {x.strip().lower() for x in args.variations.split(",") if x.strip()}
        bad_v = variations - set(ALL_VARIATIONS)
        if bad_v:
            parser.error(f"unknown variation(s) {sorted(bad_v)}; available: {','.join(ALL_VARIATIONS)}")

    n_added = synthetic.add_fonts_from_dir(args.fonts_dir) if args.fonts_dir else 0

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    width = max(6, len(str(args.start_index + args.count)))

    counts: dict[str, int] = {c: 0 for c in langs}
    for i in range(args.count):
        idx = args.start_index + i
        seed = args.seed + idx
        locale = langs[i % len(langs)]  # round-robin -> balanced languages
        counts[locale] += 1
        ticket = generate_ticket(seed=seed, locale=locale)
        image = render_receipt_image(
            ticket, seed=seed, diverse=args.diverse, distort=args.distort,
            distort_intensity=args.intensity, locale=locale, distort_variations=variations,
        )
        stem = f"receipt_{idx:0{width}d}"
        image.save(out / f"{stem}.png")
        (out / f"{stem}.json").write_text(serialize_ticket(ticket), encoding="utf-8")
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{args.count} ...", flush=True)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": args.count,
        "start_index": args.start_index,
        "languages": langs,
        "per_language": counts,
        "diverse": args.diverse,
        "distort": args.distort,
        "variations": "all" if variations is None else sorted(variations),
        "intensity": args.intensity,
        "seed": args.seed,
        "fonts_dir": args.fonts_dir,
        "extra_fonts_loaded": n_added,
        "font_pool_size": len(synthetic._FONT_POOL),
        "generator": "receipt_vlm.data.synthetic",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    mode = []
    if args.diverse:
        mode.append("diverse")
    if args.distort:
        mode.append(f"distort={args.intensity}/{manifest['variations']}")
    print(f"Generated {args.count} receipts in {out}" + (f" ({', '.join(mode)})" if mode else ""))
    print(f"  per language: {counts} | fonts in pool: {len(synthetic._FONT_POOL)}")
    print(f"  manifest: {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
