"""Pre-annote les vraies photos avec Groq, pour relecture a la main ensuite.

Pour chaque image, fait tourner l'extraction Groq et ecrit un label canonique, plus un
review_status.json (tout a false au depart) et un splits.json fige une fois pour toutes.

Ces labels ne sont PAS de la verite terrain tant qu'un humain ne les a pas relus. Le
split de test refuse d'ailleurs les labels non relus : c'est volontaire, sinon on
mesurerait le modele contre les erreurs d'un autre modele.

Demande GROQ_API_KEY.

    python scripts/pseudo_label.py --images ../data/raw/images_tickets_caisse \
        --output data/real_labels
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.real_photos import (  # noqa: E402
    REVIEW_FILENAME,
    SPLITS_FILENAME,
    freeze_splits,
    list_receipt_images,
)
from receipt_vlm.data.schema import serialize_ticket, ticket_from_dict  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, help="dossier des photos de tickets")
    parser.add_argument("--output", required=True, help="dossier ou ecrire les labels")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-annote meme les images qui ont deja un label")
    parser.add_argument("--test-fraction", type=float, default=0.3)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    args = parser.parse_args()

    # Le provider Groq n'accepte que le mode JSON.
    os.environ["RECEIPT_VLM_MODE"] = "json"

    from receipt_ocr.env import load_project_env

    load_project_env()  # recupere GROQ_API_KEY (ou l'ancien groq_key) depuis dev_ocr/.env

    from receipt_ocr.backends.vlm.extraction import run_vlm_extraction
    from receipt_ocr.backends.vlm.groq_provider import GroqProvider
    from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError
    from receipt_ocr.vlm_parse import try_parse_vlm_json

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    review_path = output / REVIEW_FILENAME
    review: dict = (
        json.loads(review_path.read_text(encoding="utf-8"))
        if review_path.exists()
        else {}
    )

    provider = GroqProvider()
    images = list_receipt_images(args.images)
    print(f"Found {len(images)} images in {args.images}")

    n_done, n_failed = 0, 0
    for image_path in images:
        label_path = output / (image_path.stem + ".json")
        if label_path.exists() and not args.overwrite:
            continue
        try:
            raw = run_vlm_extraction(provider, str(image_path))
        except (OcrBackendError, ReceiptParseError) as exc:
            print(f"  FAILED {image_path.name}: {exc}")
            n_failed += 1
            continue

        parsed = try_parse_vlm_json(raw)
        if parsed is None:
            print(f"  FAILED {image_path.name}: unparseable output")
            n_failed += 1
            continue

        ticket = ticket_from_dict(parsed)
        label_path.write_text(serialize_ticket(ticket), encoding="utf-8")
        review.setdefault(image_path.name, {"reviewed": False})
        n_done += 1
        print(f"  OK {image_path.name}: {len(ticket.produits)} produits")

    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Labelled {n_done}, failed {n_failed}. Review flags: {review_path}")

    if not (output / SPLITS_FILENAME).exists():
        labelled = [p.name for p in images if (output / (p.stem + ".json")).exists()]
        splits = freeze_splits(
            labelled, output,
            test_fraction=args.test_fraction, val_fraction=args.val_fraction,
        )
        print(
            f"Frozen splits: {len(splits['train'])} train / "
            f"{len(splits['val'])} val / {len(splits['test'])} test"
        )
        print(f"Les labels du split de test sont a relire a la main dans {review_path.name} : "
              "tant qu'ils sont a false, l'eval les ignore.")


if __name__ == "__main__":
    main()
