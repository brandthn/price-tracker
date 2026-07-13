"""Compare tous les backends OCR sur un meme jeu de tickets reels.

Paddle, PP-OCRv4, le VLM hybride, l'OCR-VLM maison, Groq et Moondream rendent chacun un
Ticket canonique, et tous sont notes avec les memes metriques.

La metrique qui compte ici est read_acc (1 - CER sur le texte lisible concatene) : les
F1 et ANLS s'etranglent des que le format ou la devise different, alors que read_acc
repond juste a "est-ce que les caracteres ont ete lus". C'est la seule qui permette de
comparer un OCR classique et un VLM sans biais.

Un backend dont la dependance, le checkpoint ou la cle API manque est saute, il ne fait
pas tomber la comparaison. Prevu pour tourner sur Kaggle (GPU + internet).

    python scripts/evaluate_all_backends.py --backends paddle hybrid ocrvlm groq
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent))   # receipt_vlm package
sys.path.insert(0, str(_SCRIPTS))          # sibling scripts (evaluate_ocr_vlm)

import evaluate_ocr_vlm as ev  # noqa: E402  on reutilise son score / predict / tokenizer
from receipt_vlm.data.real_photos import load_real_samples  # noqa: E402
from receipt_vlm.data.schema import Ticket, ticket_from_dict, ticket_from_json  # noqa: E402

# Le jeu de test francais commun a tous les backends.
FRENCH_IMAGES = _SCRIPTS.parents[1] / "data/raw/images_tickets_caisse"
FRENCH_LABELS = _SCRIPTS.parent / "data/real_labels"


class SkipBackend(Exception):
    """Levee quand une dependance, un checkpoint ou une cle manque : on saute la colonne."""


def _run_per_image(samples, infer, name):
    """Une image qui plante ne doit pas faire tomber tout le backend : elle rend un Ticket vide."""
    preds, errs = [], 0
    for s in samples:
        try:
            preds.append(infer(s))
        except Exception as e:
            errs += 1
            if errs <= 3:
                print(f"  [{name}] {Path(str(s.image)).name}: {type(e).__name__}: {e}")
            preds.append(Ticket())
    if errs:
        print(f"  [{name}] {errs}/{len(samples)} images errored -> empty ticket")
    return preds


# Chaque backend rend une liste de Ticket alignee sur `samples`.


def run_paddle(samples, cfg, name="paddle"):
    try:
        from receipt_ocr.extract_receipt import build_backend, extract_receipt
    except Exception as e:
        raise SkipBackend(f"receipt_ocr/paddle not importable: {e}")
    backend = build_backend(name)  # instancie PaddleOCR, qui telecharge ses modeles
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
    except Exception as e:
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
    except Exception as e:
        raise SkipBackend(f"Moondream unavailable (need moondream pkg + .mf weights): {e}")
    return _run_vlm_provider(samples, provider, "moondream")


def run_ocrvlm(samples, cfg):
    ckpt, tok = cfg.get("ocrvlm_checkpoint"), cfg.get("ocrvlm_tokenizer")
    if not ckpt or not Path(ckpt).is_file():
        raise SkipBackend(f"checkpoint OcrVLM introuvable : {ckpt}")
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
    p.add_argument("--limit", type=int, default=0, help="plafonne le nombre de tickets (0 = tous)")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--device", default=None, help="cuda ou cpu (par defaut : auto)")
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
        except Exception as e:
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
