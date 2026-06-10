"""Generate synthetic French receipts with perfect canonical labels.

Usage:
    python scripts/generate_synthetic.py --n 5000 --output data/synthetic
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
    args = parser.parse_args()

    paths = save_dataset(args.n, args.output, seed=args.seed)
    print(f"Generated {len(paths)} receipts in {args.output}")


if __name__ == "__main__":
    main()
