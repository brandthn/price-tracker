"""Generate synthetic French receipts with perfect canonical labels.

Usage:
    python scripts/generate_synthetic.py --n 5000 --output data/synthetic
    python scripts/generate_synthetic.py --n 100 --output data/synthetic_preview_varied \\
        --diverse --distort --distort-intensity heavy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.synthetic import save_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=2000, help="number of receipts")
    parser.add_argument("--output", default="data/synthetic", help="output directory")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--diverse",
        action="store_true",
        help="multi-style layouts, colour palettes, pre-render printer noise",
    )
    parser.add_argument(
        "--distort",
        action="store_true",
        help="post-render capture distortions (rotation, perspective, blur, JPEG, …)",
    )
    parser.add_argument(
        "--distort-intensity",
        choices=("light", "medium", "heavy"),
        default="medium",
        help="strength of post-render distortions (default: medium)",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="first receipt index in filenames (for appending to an existing folder)",
    )
    args = parser.parse_args()

    paths = save_dataset(
        args.n,
        args.output,
        seed=args.seed,
        diverse=args.diverse,
        distort=args.distort,
        distort_intensity=args.distort_intensity,
        start_index=args.start_index,
    )
    mode = []
    if args.diverse:
        mode.append("diverse layouts")
    if args.distort:
        mode.append(f"distort={args.distort_intensity}")
    extra = f" ({', '.join(mode)})" if mode else ""
    print(f"Generated {len(paths)} receipts in {args.output}{extra}")


if __name__ == "__main__":
    main()
