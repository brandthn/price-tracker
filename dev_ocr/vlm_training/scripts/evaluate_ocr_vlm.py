"""Evaluate the from-scratch OCR-VLM (`OcrVLM`) on real receipts + held-out synthetic.

Loads an ``ocr_vlm_epoch*.pt`` checkpoint + its char tokenizer, runs the model end-to-end
(``prepare_ocr_pixels`` -> ``generate`` -> ``Ticket``) and scores predictions with the shared
``evaluate_tickets`` metrics. Prints a per-dataset + aggregate acceptance table and a few
qualitative pred-vs-gold dumps, so we can read the sim-to-real gap after M1.

Unlike ``scripts/evaluate.py`` (hardwired to the CLIP+SmolLM2 model), this one drives the
from-scratch stack. No CLIP normalization, no constrained decoding — greedy ``generate``.

Usage:
    python scripts/evaluate_ocr_vlm.py \
        --checkpoint checkpoints/ocr_vlm_epoch040_loss0.2265.pt \
        --tokenizer checkpoints/tokenizer_20260607_0900.json \
        --synthetic 128
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
from PIL import Image  # noqa: E402

from receipt_vlm.data.dataset import ReceiptSample, _load_image  # noqa: E402
from receipt_vlm.data.ocr_transform import prepare_ocr_pixels  # noqa: E402
from receipt_vlm.data.real_photos import load_real_samples  # noqa: E402
from receipt_vlm.data.schema import Ticket  # noqa: E402
from receipt_vlm.data.synthetic import generate_ticket, render_receipt_image  # noqa: E402
from receipt_vlm.data.tokenizer import CharTokenizer  # noqa: E402
from receipt_vlm.models.ocr_vlm import OcrVLM  # noqa: E402
from receipt_vlm.utils.metrics import evaluate_tickets  # noqa: E402

# Real datasets with the {splits,review_status}.json convention. Paths are resolved relative to
# dev_ocr/data (parents[2] == dev_ocr). SRD's test split is Groq-pseudo-labelled (unreviewed),
# so it is only included with --include-unreviewed.
_DATA = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DATASETS = {
    "cord_v2": (_DATA / "raw/cord_v2", _DATA / "labels/cord_v2"),
    "wildreceipt": (_DATA / "raw/wildreceipt", _DATA / "labels/wildreceipt"),
    "trainingdatapro": (_DATA / "raw/trainingdatapro", _DATA / "labels/trainingdatapro"),
    "expressexpense_srd": (_DATA / "raw/expressexpense_srd", _DATA / "labels/expressexpense_srd"),
}


def _resolve_tokenizer(checkpoint: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    ckpt_dir = checkpoint.parent
    for name in ("tokenizer.json", *sorted(p.name for p in ckpt_dir.glob("tokenizer*.json"))):
        if (ckpt_dir / name).is_file():
            return ckpt_dir / name
    raise FileNotFoundError(f"No tokenizer*.json next to {checkpoint} — pass --tokenizer.")


def _sample_image(sample: ReceiptSample) -> Image.Image:
    """Real samples carry a path; synthetic carry a callable (image or (image, text))."""
    img = sample.image() if callable(sample.image) else _load_image(sample.image)
    return img[0] if isinstance(img, tuple) else img


@torch.no_grad()
def predict(model: OcrVLM, samples: list[ReceiptSample], device: str,
           batch_size: int, max_len: int) -> list[Ticket]:
    preds: list[Ticket] = []
    for start in range(0, len(samples), batch_size):
        chunk = samples[start:start + batch_size]
        pixels = torch.stack(
            [torch.from_numpy(prepare_ocr_pixels(_sample_image(s))) for s in chunk]
        ).to(device)
        preds.extend(model.generate(pixels, max_len=max_len))
        print(f"    {min(start + batch_size, len(samples))}/{len(samples)}", end="\r", flush=True)
    print(" " * 40, end="\r")
    return preds


def build_synthetic(n: int, langs: list[str], seed: int) -> list[ReceiptSample]:
    samples: list[ReceiptSample] = []
    for i in range(n):
        locale = langs[i % len(langs)]
        s = seed + i
        ticket = generate_ticket(seed=s, locale=locale)
        samples.append(ReceiptSample(
            image=(lambda t=ticket, sd=s, lc=locale: render_receipt_image(
                t, seed=sd, diverse=True, distort=True, distort_intensity="light", locale=lc)),
            ticket=ticket, source="synthetic",
        ))
    return samples


ROWS = (
    ("field_f1", "Field F1"),
    ("field_precision", "Field precision"),
    ("field_recall", "Field recall"),
    ("product_recall", "Product recall"),
    ("anls", "ANLS"),
    ("price_mae", "Price MAE"),
    ("date_accuracy", "Date exact match"),
)


def print_table(results: list[tuple[str, dict]]) -> None:
    names = [name for name, _ in results]
    widths = [18] + [max(12, len(n)) for n in names]
    header = "  ".join(h.ljust(w) for h, w in zip(["Metric", *names], widths))
    print("\n" + header)
    print("-" * len(header))
    for key, label in ROWS:
        cells = [label.ljust(widths[0])]
        for (_, m), w in zip(results, widths[1:]):
            cells.append(f"{m[key]:.3f}".ljust(w))
        print("  ".join(cells))
    counts = "  ".join(f"{int(m['n_samples'])}".ljust(w) for (_, m), w in zip(results, widths[1:]))
    print("n".ljust(widths[0]) + "  " + counts)


def dump_examples(name: str, samples: list[ReceiptSample], preds: list[Ticket], k: int) -> None:
    print(f"\n--- {name}: {min(k, len(samples))} qualitative examples ---")
    for sample, pred in list(zip(samples, preds))[:k]:
        gold = sample.ticket
        print(f"  GOLD store={gold.chaine_supermarche!r} date={gold.date!r} "
              f"items={len(gold.produits)}")
        print(f"  PRED store={pred.chaine_supermarche!r} date={pred.date!r} "
              f"items={len(pred.produits)}")
        if gold.produits or pred.produits:
            g0 = gold.produits[0] if gold.produits else None
            p0 = pred.produits[0] if pred.produits else None
            print(f"       gold[0]={g0.nom_produit!r}@{g0.prix_unitaire_ou_kg if g0 else '-'} | "
                  f"pred[0]={p0.nom_produit!r}@{p0.prix_unitaire_ou_kg if p0 else '-'}")
        print()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--checkpoint", default="checkpoints/ocr_vlm_epoch040_loss0.2265.pt")
    p.add_argument("--tokenizer", default=None, help="default: tokenizer*.json next to checkpoint")
    p.add_argument("--split", default="test")
    p.add_argument("--datasets", nargs="*", default=["cord_v2", "wildreceipt", "trainingdatapro"],
                   help="keys from DEFAULT_DATASETS")
    p.add_argument("--include-unreviewed", action="store_true",
                   help="keep unreviewed labels (adds SRD's pseudo-labelled test split)")
    p.add_argument("--synthetic", type=int, default=0, help="also eval N held-out synthetic")
    p.add_argument("--synthetic-langs", default="fr,en,es,de,it")
    p.add_argument("--synthetic-seed", type=int, default=999999)
    p.add_argument("--limit", type=int, default=0, help="cap samples per dataset (0=all)")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--max-len", type=int, default=0, help="0 = model's trained max_len")
    p.add_argument("--examples", type=int, default=3)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--output", default=None)
    args = p.parse_args()

    checkpoint = Path(args.checkpoint)
    tok_path = _resolve_tokenizer(checkpoint, args.tokenizer)
    tokenizer = CharTokenizer.load(tok_path)
    model = OcrVLM.from_checkpoint(str(checkpoint), tokenizer, device=args.device)
    max_len = args.max_len or model.max_len
    print(f"model {sum(pr.numel() for pr in model.parameters())/1e6:.2f}M params | "
          f"vocab {tokenizer.vocab_size} | max_len {max_len} | device {args.device}\n"
          f"checkpoint {checkpoint.name} | tokenizer {tok_path.name}")

    results: list[tuple[str, dict]] = []
    all_preds: list[Ticket] = []
    all_golds: list[Ticket] = []

    for key in args.datasets:
        if key not in DEFAULT_DATASETS:
            raise SystemExit(f"unknown dataset {key!r}; choices: {sorted(DEFAULT_DATASETS)}")
        images_dir, labels_dir = DEFAULT_DATASETS[key]
        req = False if args.include_unreviewed else None  # None -> reviewed on the test split
        samples = load_real_samples(images_dir, labels_dir, split=args.split, require_reviewed=req)
        if args.limit:
            samples = samples[:args.limit]
        if not samples:
            print(f"[{key}] no samples in split {args.split!r} — skipping")
            continue
        print(f"[{key}] {len(samples)} receipts...")
        t0 = time.time()
        preds = predict(model, samples, args.device, args.batch_size, max_len)
        metrics = evaluate_tickets(preds, [s.ticket for s in samples])
        print(f"[{key}] done in {time.time()-t0:.0f}s")
        results.append((key, metrics))
        all_preds.extend(preds)
        all_golds.extend([s.ticket for s in samples])
        dump_examples(key, samples, preds, args.examples)

    if args.synthetic:
        langs = [c.strip() for c in args.synthetic_langs.split(",") if c.strip()]
        samples = build_synthetic(args.synthetic, langs, args.synthetic_seed)
        print(f"[synthetic] {len(samples)} held-out receipts...")
        preds = predict(model, samples, args.device, args.batch_size, max_len)
        results.append(("synthetic", evaluate_tickets(preds, [s.ticket for s in samples])))
        dump_examples("synthetic", samples, preds, args.examples)

    if len(all_golds) > 1 and len([r for r in results if r[0] != "synthetic"]) > 1:
        results.insert(0, ("REAL-all", evaluate_tickets(all_preds, all_golds)))

    if not results:
        raise SystemExit("No samples evaluated.")
    print_table(results)

    if args.output:
        import json
        Path(args.output).write_text(
            json.dumps({name: m for name, m in results}, indent=2), encoding="utf-8")
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
