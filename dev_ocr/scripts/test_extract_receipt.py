#!/usr/bin/env python3
"""Appelle extract_receipt() sur une image comme le ferait un appelant externe,
et vérifie que le JSON qui sort respecte bien le schéma.

    python scripts/test_extract_receipt.py
    python scripts/test_extract_receipt.py path/to/ticket.jpg --backend paddle

Variables utiles : RECEIPT_OCR_BACKEND, RECEIPT_VLM_MODEL, RECEIPT_VLM_MODEL_PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_IMAGE = ROOT / "data" / "raw" / "images_tickets_caisse" / "image_2.jpg"


def _schema_errors(result: dict) -> list[str]:
    if "ticket" not in result:
        return ["pas de clé 'ticket'"]

    errors: list[str] = []
    ticket = result["ticket"]
    for key in ("date", "chaine_supermarche", "adresse", "produits"):
        if key not in ticket:
            errors.append(f"ticket : clé '{key}' manquante")

    produits = ticket.get("produits")
    if not isinstance(produits, list):
        errors.append("'produits' devrait être une liste")
        return errors

    for i, product in enumerate(produits):
        for field in ("nom_produit", "prix_unitaire_ou_kg", "unites"):
            if field not in product:
                errors.append(f"produits[{i}] : '{field}' manquant")
        prix = product.get("prix_unitaire_ou_kg")
        if prix is not None and not isinstance(prix, (int, float)):
            errors.append(f"produits[{i}].prix_unitaire_ou_kg pas numérique")
        unites = product.get("unites")
        if unites is not None and not isinstance(unites, int):
            errors.append(f"produits[{i}].unites pas un entier")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste extract_receipt sur un ticket.")
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    parser.add_argument(
        "--backend", choices=("paddle", "ppocrv4", "vlm"), default="ppocrv4"
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"image introuvable : {image_path}", file=sys.stderr)
        return 1

    os.environ["RECEIPT_OCR_BACKEND"] = args.backend

    from receipt_ocr import extract_receipt, reset_default_backend
    from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError

    reset_default_backend()

    # Le premier appel charge les modèles : compter une bonne minute.
    t0 = time.perf_counter()
    try:
        result = extract_receipt(str(image_path))
    except (FileNotFoundError, OcrBackendError, ReceiptParseError) as exc:
        print(f"échec : {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0

    errors = _schema_errors(result)
    if errors:
        print(f"schéma KO ({elapsed:.1f}s)")
        for err in errors:
            print(f"  - {err}")
    else:
        ticket = result["ticket"]
        print(
            f"{elapsed:.1f}s — {ticket['chaine_supermarche']!r}, "
            f"{ticket['date']!r}, {len(ticket['produits'])} produit(s)"
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
