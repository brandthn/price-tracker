"""Genere des tickets synthetiques avec leurs labels.

On choisit combien, dans quelles langues, avec quelles deformations et a quelle
intensite. Un manifest.json garde la config exacte du run, pour pouvoir le refaire.

Le levier le plus efficace n'est pas le nombre de tickets mais la diversite des polices
(--fonts-dir) : c'est ce qui empeche le modele d'apprendre a lire une seule typo.

    python scripts/generate_synthetic.py --n 5000 --output data/synthetic --diverse --distort
    python scripts/generate_synthetic.py --count 10000 --languages fr,en,es,de,it \
        --diverse --distort --intensity heavy --fonts-dir /chemin/vers/ttf
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
                        help="combien de tickets")
    parser.add_argument("--output", "--out", dest="output", default="data/synthetic",
                        help="dossier de sortie")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--languages", "--langs", dest="languages", default="fr",
                        help=f"comma list of Latin-script locales. Available: {','.join(available_locales())}")
    parser.add_argument("--diverse", action="store_true",
                        help="plusieurs mises en page, palettes, et bruit d'imprimante avant rendu")
    parser.add_argument("--distort", action="store_true",
                        help="deformations de prise de vue apres rendu (cf. --variations)")
    parser.add_argument("--distort-intensity", "--intensity", dest="intensity",
                        choices=("light", "medium", "heavy"), default="medium")
    parser.add_argument("--variations", default="all",
                        help=f"'all', 'none', or comma subset of: {','.join(ALL_VARIATIONS)}")
    parser.add_argument("--fonts-dir", default=None,
                        help="des .ttf/.otf en plus : c'est le meilleur levier de diversite")
    parser.add_argument("--start-index", type=int, default=0,
                        help="index du premier ticket, pour completer un dossier existant")
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
        locale = langs[i % len(langs)]  # tourniquet : les langues restent equilibrees
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
