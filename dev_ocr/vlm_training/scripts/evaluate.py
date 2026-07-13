"""Evalue le modele hybride sur le jeu de test, face a Groq.

Sort le tableau d'acceptation : F1 par champ, ANLS, rappel produit, MAE des prix, date
exacte, taux de JSON valide.

    python scripts/evaluate.py --checkpoint checkpoints/receipt_vlm_500m_merged.pt \
        --images ../data/raw/images_tickets_caisse --labels data/real_labels \
        --split test --baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.real_photos import load_real_samples  # noqa: E402
from receipt_vlm.data.schema import Ticket, ticket_from_dict, ticket_from_json  # noqa: E402
from receipt_vlm.utils.metrics import evaluate_tickets  # noqa: E402


def _validate_pass(raw: str) -> bool:
    from receipt_ocr.vlm_validate import validate_vlm_output

    return validate_vlm_output("json", raw).ok


def run_hybrid(samples, checkpoint: str) -> tuple[list[Ticket], list[bool], list[bool]]:
    import torch
    from PIL import Image

    from receipt_vlm.data.augmentation import clip_normalize_pil
    from receipt_vlm.models.vlm import ReceiptVLM

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ReceiptVLM.from_merged_checkpoint(checkpoint, device=device)

    predictions, valid_json, validate_ok = [], [], []
    for sample in samples:
        image = Image.open(str(sample.image))
        pixels = torch.from_numpy(clip_normalize_pil(image)).unsqueeze(0).to(device)
        raw = model.generate(pixels, constrained=True)[0]
        try:
            predictions.append(ticket_from_json(raw))
            valid_json.append(True)
        except (json.JSONDecodeError, ValueError):
            predictions.append(Ticket())
            valid_json.append(False)
        validate_ok.append(_validate_pass(raw))
    return predictions, valid_json, validate_ok


def run_groq(samples) -> tuple[list[Ticket], list[bool], list[bool]]:
    import os

    os.environ["RECEIPT_VLM_MODE"] = "json"

    from receipt_ocr.env import load_project_env

    load_project_env()  # recupere GROQ_API_KEY (ou l'ancien groq_key) depuis dev_ocr/.env

    from receipt_ocr.backends.vlm.extraction import run_vlm_extraction
    from receipt_ocr.backends.vlm.groq_provider import GroqProvider
    from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError
    from receipt_ocr.vlm_parse import try_parse_vlm_json

    provider = GroqProvider()
    predictions, valid_json, validate_ok = [], [], []
    for sample in samples:
        try:
            raw = run_vlm_extraction(provider, str(sample.image))
        except (OcrBackendError, ReceiptParseError):
            predictions.append(Ticket())
            valid_json.append(False)
            validate_ok.append(False)
            continue
        parsed = try_parse_vlm_json(raw)
        predictions.append(ticket_from_dict(parsed) if parsed else Ticket())
        valid_json.append(parsed is not None)
        validate_ok.append(_validate_pass(raw))
    return predictions, valid_json, validate_ok


def summarize(name: str, samples, predictions, valid_json, validate_ok) -> dict:
    golds = [sample.ticket for sample in samples]
    metrics = evaluate_tickets(predictions, golds)
    metrics["valid_json_rate"] = sum(valid_json) / len(valid_json)
    metrics["vlm_validate_pass_rate"] = sum(validate_ok) / len(validate_ok)
    metrics["engine"] = name
    return metrics


ROWS = (
    ("field_f1", "Field F1", "> 0.85"),
    ("product_recall", "Product recall", "> 0.90"),
    ("price_mae", "Price MAE (EUR)", "< 0.05"),
    ("date_accuracy", "Date exact match", "> 0.90"),
    ("anls", "ANLS", "> 0.80"),
    ("vlm_validate_pass_rate", "vlm_validate pass", "> 0.80"),
    ("valid_json_rate", "Valid JSON rate", "= 1.00"),
)


def print_table(results: list[dict]) -> None:
    headers = ["Metric", "Target"] + [r["engine"] for r in results]
    widths = [22, 8] + [max(12, len(h)) for h in headers[2:]]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print("\n" + line)
    print("-" * len(line))
    for key, label, target in ROWS:
        cells = [label.ljust(widths[0]), target.ljust(widths[1])]
        for result, width in zip(results, widths[2:]):
            cells.append(f"{result[key]:.3f}".ljust(width))
        print("  ".join(cells))
    print(f"\nn = {int(results[0]['n_samples'])} held-out receipts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="le .pt fusionne")
    parser.add_argument("--images", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--baseline", action="store_true",
                        help="fait aussi tourner Groq en comparaison (demande GROQ_API_KEY)")
    parser.add_argument("--output", help="fichier JSON de resultats (optionnel)")
    args = parser.parse_args()

    samples = load_real_samples(args.images, args.labels, split=args.split)
    if not samples:
        raise SystemExit(
            f"No reviewed samples in split {args.split!r} — "
            "check labels and review_status.json."
        )
    print(f"Evaluating on {len(samples)} {args.split} receipts")

    results = [summarize("receipt-vlm-500m", samples, *run_hybrid(samples, args.checkpoint))]
    if args.baseline:
        results.append(summarize("groq-llama4-scout", samples, *run_groq(samples)))

    print_table(results)
    if args.output:
        Path(args.output).write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
        print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
