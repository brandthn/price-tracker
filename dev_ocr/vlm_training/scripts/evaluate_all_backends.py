"""Compare every OCR backend on one common real test set (French receipt photos).

Paddle, PP-OCRv4, hybrid CLIP+SmolLM2 VLM, from-scratch OCR-VLM, Groq, and Moondream each turn an image
into a canonical :class:`Ticket`; all are scored by the **same** metrics (field F1, product recall,
ANLS, price MAE, date EM) plus **read_acc** (1-CER over concatenated readable text — the fair
cross-backend "did the glyphs get read" signal, robust to format/currency) and a `valid` rate. Prints
one comparison table (metric rows x backend columns) and writes JSON.

Backends whose dependency / checkpoint / API key is missing are **skipped with a note**, never crash.
Meant to run on Kaggle (GPU + internet); see ``notebooks/evaluate_all_backends_kaggle.ipynb``.

Usage:
    python scripts/evaluate_all_backends.py --backends paddle hybrid ocrvlm groq \
        --hybrid-checkpoint checkpoints/receipt_vlm_500m_merged.pt \
        --ocrvlm-checkpoint checkpoints/ocr_vlm_epoch050_loss0.3619.pt \
        --ocrvlm-tokenizer checkpoints/tokenizer_20260607_0900.json
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent))   # receipt_vlm package
sys.path.insert(0, str(_SCRIPTS))          # sibling scripts (evaluate_ocr_vlm)

import evaluate_ocr_vlm as ev  # noqa: E402  reuse score / predict / OcrVLM / CharTokenizer
from receipt_vlm.data.real_photos import load_real_samples  # noqa: E402
from receipt_vlm.data.schema import Ticket, ticket_from_dict, ticket_from_json  # noqa: E402

# Defaults for the common French test set.
# _SCRIPTS = dev_ocr/vlm_training/scripts -> parent=vlm_training, parents[1]=dev_ocr.
FRENCH_IMAGES = _SCRIPTS.parents[1] / "data/raw/images_tickets_caisse"   # dev_ocr/data/...
FRENCH_LABELS = _SCRIPTS.parent / "data/real_labels"                      # vlm_training/data/real_labels


class SkipBackend(Exception):
    """Raised by a backend when its dep/checkpoint/key is unavailable -> skip its column."""


def _run_per_image(samples, infer, name):
    """Apply ``infer(sample) -> Ticket`` per image; per-image errors -> empty Ticket (not fatal)."""
    preds, errs = [], 0
    for s in samples:
        try:
            preds.append(infer(s))
        except Exception as e:  # noqa: BLE001 - one bad image shouldn't sink the backend
            errs += 1
            if errs <= 3:
                print(f"  [{name}] {Path(str(s.image)).name}: {type(e).__name__}: {e}")
            preds.append(Ticket())
    if errs:
        print(f"  [{name}] {errs}/{len(samples)} images errored -> empty ticket")
    return preds


# ----------------------------------------------------------------------
# Backend adapters: each returns list[Ticket] aligned with `samples`.


def run_paddle(samples, cfg, name="paddle"):
    try:
        from receipt_ocr.extract_receipt import build_backend, extract_receipt
    except Exception as e:  # noqa: BLE001
        raise SkipBackend(f"receipt_ocr/paddle not importable: {e}")
    backend = build_backend(name)  # instantiates PaddleOCR (auto-downloads models)
    return _run_per_image(samples, lambda s: ticket_from_dict(extract_receipt(str(s.image), backend)), name)


def run_ppocrv4(samples, cfg):
    return run_paddle(samples, cfg, name="ppocrv4")


def run_hybrid(samples, cfg):
    ckpt = cfg.get("hybrid_checkpoint")
    if not ckpt or not Path(ckpt).is_file():
        raise SkipBackend(f"hybrid checkpoint not found: {ckpt}")
    import torch
    from PIL import Image
    from receipt_vlm.data.augmentation import clip_normalize_pil
    from receipt_vlm.models.vlm import ReceiptVLM

    # Force a single dtype: the merged checkpoint mixes float32 (CLIP) and bf16 (SmolLM2), which
    # otherwise throws "mat1/mat2 dtype mismatch" against float32 pixels. fp32 fits a T4 (~1.8 GB).
    model = ReceiptVLM.from_merged_checkpoint(ckpt, device=cfg["device"]).float()

    def infer(s):
        px = torch.from_numpy(clip_normalize_pil(Image.open(str(s.image)))).unsqueeze(0)
        px = px.to(cfg["device"], dtype=torch.float32)
        return ticket_from_json(model.generate(px, constrained=True)[0])

    return _run_per_image(samples, infer, "hybrid")


def _run_vlm_provider(samples, provider, name):
    from receipt_ocr.backends.vlm.extraction import run_vlm_extraction
    from receipt_ocr.vlm_parse import try_parse_vlm_json

    def infer(s):
        parsed = try_parse_vlm_json(run_vlm_extraction(provider, str(s.image)))
        return ticket_from_dict(parsed) if parsed else Ticket()

    return _run_per_image(samples, infer, name)


def run_groq(samples, cfg):
    import os

    os.environ["RECEIPT_VLM_MODE"] = "json"  # GroqProvider.__init__ validates this — set BEFORE ctor
    from receipt_ocr.env import load_project_env

    load_project_env()  # GROQ_API_KEY / groq_key from dev_ocr/.env (or Kaggle Secret in env)
    try:
        from receipt_ocr.backends.vlm.groq_provider import GroqProvider

        provider = GroqProvider()
    except Exception as e:  # noqa: BLE001 - missing key / pkg / mode
        raise SkipBackend(f"Groq unavailable (key/pkg?): {e}")
    return _run_vlm_provider(samples, provider, "groq")


def run_moondream(samples, cfg):
    import os

    os.environ["RECEIPT_VLM_MODE"] = "json"  # set BEFORE provider ctor (mode validated there)
    if cfg.get("moondream_weights"):
        os.environ.setdefault("MOONDREAM_MODEL_DIR", cfg["moondream_weights"])
    try:
        from receipt_ocr.backends.vlm.moondream_provider import MoondreamProvider

        provider = MoondreamProvider()  # needs the `moondream` pkg + local .mf int8 weights
    except Exception as e:  # noqa: BLE001 - pkg/weights not present
        raise SkipBackend(f"Moondream unavailable (need moondream pkg + .mf weights): {e}")
    return _run_vlm_provider(samples, provider, "moondream")


def run_ocrvlm(samples, cfg):
    ckpt, tok = cfg.get("ocrvlm_checkpoint"), cfg.get("ocrvlm_tokenizer")
    if not ckpt or not Path(ckpt).is_file():
        raise SkipBackend(f"from-scratch checkpoint not found: {ckpt}")
    tok_path = ev._resolve_tokenizer(Path(ckpt), tok)
    tokenizer = ev.CharTokenizer.load(tok_path)
    model = ev.OcrVLM.from_checkpoint(str(ckpt), tokenizer, device=cfg["device"])
    return ev.predict(model, samples, cfg["device"], cfg["batch_size"], model.max_len)


BACKENDS = {
    "paddle": run_paddle,
    "ppocrv4": run_ppocrv4,
    "hybrid": run_hybrid,
    "groq": run_groq,
    "moondream": run_moondream,
    "ocrvlm": run_ocrvlm,
}


# ----------------------------------------------------------------------
# Metrics + table.

ROWS = (
    ("read_acc", "Read acc (1-CER)"),
    ("valid", "Valid (non-empty)"),
    ("product_recall", "Product recall"),
    ("field_f1", "Field F1"),
    ("anls", "ANLS"),
    ("price_mae", "Price MAE"),
    ("date_accuracy", "Date exact match"),
)


def scored(preds, golds):
    m = ev.score(preds, golds)  # evaluate_tickets + read_acc
    m["valid"] = sum(1 for t in preds if t.chaine_supermarche or t.produits) / max(1, len(preds))
    return m


def print_comparison(results):
    names = [n for n, _ in results]
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


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backends", nargs="*", default=list(BACKENDS),
                   help=f"subset of {list(BACKENDS)} (missing deps skip automatically)")
    p.add_argument("--french-images", default=str(FRENCH_IMAGES))
    p.add_argument("--french-labels", default=str(FRENCH_LABELS))
    p.add_argument("--hybrid-checkpoint", default=None)
    p.add_argument("--ocrvlm-checkpoint", default=None)
    p.add_argument("--ocrvlm-tokenizer", default=None)
    p.add_argument("--moondream-weights", default=None)
    p.add_argument("--limit", type=int, default=0, help="cap number of test receipts (0=all)")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--device", default=None, help="cuda|cpu (default: auto)")
    p.add_argument("--output", default=None)
    args = p.parse_args()

    import torch

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    cfg = {
        "device": device, "batch_size": args.batch_size,
        "hybrid_checkpoint": args.hybrid_checkpoint,
        "ocrvlm_checkpoint": args.ocrvlm_checkpoint, "ocrvlm_tokenizer": args.ocrvlm_tokenizer,
        "moondream_weights": args.moondream_weights,
    }

    samples = load_real_samples(args.french_images, args.french_labels,
                                split=None, require_reviewed=False)
    if args.limit:
        samples = samples[:args.limit]
    if not samples:
        raise SystemExit(f"No French test samples under {args.french_images} / {args.french_labels}")
    golds = [s.ticket for s in samples]
    print(f"Common test set: {len(samples)} French receipts | device {device}")

    results, skipped = [], []
    for name in args.backends:
        if name not in BACKENDS:
            print(f"[{name}] unknown backend; choices: {list(BACKENDS)}")
            continue
        print(f"\n=== {name} ===")
        import time
        t0 = time.time()
        try:
            preds = BACKENDS[name](samples, cfg)
        except (SkipBackend, ImportError) as e:  # missing dep/key/checkpoint -> clean skip
            print(f"[{name}] SKIPPED: {e}")
            skipped.append((name, str(e)))
            continue
        except Exception as e:  # noqa: BLE001 - a real backend bug shouldn't kill the comparison
            print(f"[{name}] SKIPPED (error): {e}")
            traceback.print_exc()
            skipped.append((name, str(e)))
            continue
        results.append((name, scored(preds, golds)))
        print(f"[{name}] done in {time.time()-t0:.0f}s")

    if not results:
        raise SystemExit("No backend produced results.")
    print_comparison(results)
    if skipped:
        print("\nskipped:", ", ".join(f"{n} ({why})" for n, why in skipped))

    if args.output:
        import json

        Path(args.output).write_text(
            json.dumps({"results": {n: m for n, m in results},
                        "skipped": dict(skipped), "n_samples": len(samples)}, indent=2),
            encoding="utf-8")
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
