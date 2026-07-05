"""Train the from-scratch OCR-VLM (encoder + decoder) — resumable, checkpoint-per-epoch.

Image -> OcrEncoder -> OcrDecoder -> linearized schema -> Ticket. Trains on on-the-fly
multilingual synthetic (infinite variety, no PNGs on disk) with perfect labels. Designed for
free-tier multi-session GPUs: every epoch writes a resumable checkpoint
``ocr_vlm_epoch{NN}_loss{L}.pt`` (model + optimizer + config) into ``--checkpoint-dir``; on
restart it auto-resumes from the latest, so a crash costs <= 1 epoch. A fixed tokenizer
(``tokenizer.json``, default broad-Latin charset) keeps the vocab identical across sessions.

Usage:
    # M0 overfit sanity (tiny):
    python scripts/train_ocr_vlm.py --n 8 --epochs 250 --lr 5e-4 --checkpoint-dir logs/ocr_m0
    # M1 read pretraining (scaled; Kaggle T4):
    python scripts/train_ocr_vlm.py --n 30000 --languages fr,en,es,de,it --epochs 40 \
        --batch-size 24 --num-workers 2 --checkpoint-dir /kaggle/working/ocr_ckpts
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

from receipt_vlm.data.dataset import ReceiptSample, _load_image  # noqa: E402
from receipt_vlm.data.lin_schema import ticket_to_linear  # noqa: E402
from receipt_vlm.data.ocr_dataset import OcrDataset, make_ocr_collate  # noqa: E402
from receipt_vlm.data.ocr_transform import IMG_H, IMG_W, prepare_ocr_pixels  # noqa: E402
from receipt_vlm.data.synthetic import generate_ticket, render_receipt_image  # noqa: E402
from receipt_vlm.data.tokenizer import CharTokenizer  # noqa: E402
from receipt_vlm.models.ocr_vlm import OcrVLM  # noqa: E402
from receipt_vlm.utils.metrics import evaluate_tickets  # noqa: E402


# ----------------------------------------------------------------------
# Data: on-the-fly synthetic (module-level factory so DataLoader workers can fork it).


def _render_factory(seed: int, ticket, locale: str, distort: bool, intensity: str):
    def render():
        return render_receipt_image(
            ticket, seed=seed, diverse=True, distort=distort,
            distort_intensity=intensity, locale=locale,
        )
    return render


def build_synthetic_samples(n, langs, seed, distort, intensity) -> list[ReceiptSample]:
    samples: list[ReceiptSample] = []
    for i in range(n):
        locale = langs[i % len(langs)]
        s = seed + i
        ticket = generate_ticket(seed=s, locale=locale)
        samples.append(ReceiptSample(
            image=_render_factory(s, ticket, locale, distort, intensity),
            ticket=ticket, source="synthetic",
        ))
    return samples


# ----------------------------------------------------------------------
# Resumable checkpointing.


def _epoch_of(path: Path) -> int:
    m = re.search(r"_epoch(\d+)_", path.name)
    return int(m.group(1)) if m else -1


def _latest_checkpoint(ckpt_dir: Path):
    files = sorted(ckpt_dir.glob("ocr_vlm_epoch*.pt"), key=_epoch_of)
    return files[-1] if files else None


def _save_checkpoint(ckpt_dir: Path, model, optimizer, epoch: int, val_loss: float) -> None:
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = ckpt_dir / f"ocr_vlm_epoch{epoch:03d}_loss{val_loss:.4f}.pt"
    payload = {
        "model_state": model.state_dict(),
        "optim_state": optimizer.state_dict(),
        "config": model.config,
        "epoch": epoch,
    }
    tmp = path.with_suffix(".pt.tmp")
    torch.save(payload, tmp)
    tmp.replace(path)
    # "_epoch" in the line lets a stdout-watching notebook mirror it to a Kaggle Dataset.
    print(f"Checkpoint saved: {path} ({path.stat().st_size / 1e6:.0f} MB)", flush=True)


def _prune_checkpoints(ckpt_dir: Path, keep_last: int) -> None:
    """Keep only the newest ``keep_last`` epoch checkpoints (bounds the pushed folder size)."""
    if keep_last <= 0:
        return
    files = sorted(ckpt_dir.glob("ocr_vlm_epoch*.pt"), key=_epoch_of)
    for old in files[:-keep_last]:
        old.unlink(missing_ok=True)


# ----------------------------------------------------------------------


@torch.no_grad()
def _quick_eval(model, samples, device, max_len, limit) -> dict:
    model.eval()
    subset = samples[:limit]
    px = torch.stack([
        torch.from_numpy(prepare_ocr_pixels(_load_image(s.image))) for s in subset
    ]).to(device)
    preds = model.generate(px, max_len=max_len)
    metrics = evaluate_tickets(preds, [s.ticket for s in subset])
    metrics["valid"] = sum(1 for t in preds if t.chaine_supermarche or t.produits) / len(preds)
    return metrics


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=20000, help="synthetic receipts per epoch")
    p.add_argument("--languages", default="fr,en,es,de,it")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch-size", type=int, default=24)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--embed-dim", type=int, default=256)
    p.add_argument("--enc-depth", type=int, default=4)
    p.add_argument("--dec-depth", type=int, default=4)
    p.add_argument("--heads", type=int, default=8)
    p.add_argument("--max-len", type=int, default=640)
    p.add_argument("--num-workers", type=int, default=0)
    p.add_argument("--distort", action="store_true")
    p.add_argument("--distort-intensity", default="light", choices=("light", "medium", "heavy"))
    p.add_argument("--eval-every", type=int, default=1, help="epochs between synthetic evals (0=off)")
    p.add_argument("--eval-n", type=int, default=16)
    p.add_argument("--eval-max-len", type=int, default=560)
    p.add_argument("--log-every", type=int, default=100, help="batches between heartbeat prints")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--checkpoint-dir", default="logs/ocr_vlm")
    p.add_argument("--keep-last", type=int, default=3,
                   help="prune to the newest N epoch checkpoints (bounds pushed folder size; 0=keep all)")
    args = p.parse_args()

    torch.manual_seed(args.seed)
    langs = [c.strip() for c in args.languages.split(",") if c.strip()]
    ckpt_dir = Path(args.checkpoint_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    device = args.device

    # Fixed tokenizer (persist so resumes across sessions share one vocab).
    tok_path = ckpt_dir / "tokenizer.json"
    tokenizer = CharTokenizer.load(tok_path) if tok_path.is_file() else CharTokenizer.default()
    if not tok_path.is_file():
        tokenizer.save(tok_path)

    print(f"langs {langs} | n/epoch {args.n} | vocab {tokenizer.vocab_size} | device {device}", flush=True)

    dataset = OcrDataset(build_synthetic_samples(args.n, langs, args.seed, args.distort,
                                                 args.distort_intensity),
                         tokenizer, IMG_H, IMG_W, args.max_len)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True,
                        num_workers=args.num_workers, collate_fn=make_ocr_collate(tokenizer.pad_id),
                        pin_memory=(device == "cuda"), persistent_workers=args.num_workers > 0)

    model = OcrVLM(tokenizer, embed_dim=args.embed_dim, enc_depth=args.enc_depth,
                   dec_depth=args.dec_depth, num_heads=args.heads,
                   img_h=IMG_H, img_w=IMG_W, max_len=args.max_len).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    # Auto-resume from the latest epoch checkpoint in the dir.
    start_epoch = 0
    latest = _latest_checkpoint(ckpt_dir)
    if latest is not None:
        ckpt = torch.load(latest, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state"])
        optimizer.load_state_dict(ckpt["optim_state"])
        start_epoch = ckpt["epoch"]
        print(f"Resumed from {latest.name} (continue at epoch {start_epoch + 1})", flush=True)

    n_params = sum(pr.numel() for pr in model.parameters())
    print(f"OcrVLM {n_params/1e6:.2f}M params | {model.encoder.num_tokens} visual tokens | "
          f"{len(loader)} batches/epoch", flush=True)

    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler(enabled=use_amp)

    for epoch in range(start_epoch, args.epochs):
        model.train()
        start = last = time.time()
        total, nb = 0.0, 0
        for pixels, ids in loader:
            pixels = pixels.to(device, non_blocking=True)
            ids = ids.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda" if use_amp else "cpu", enabled=use_amp):
                _, loss = model(pixels, ids)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            total += loss.item(); nb += 1
            if args.log_every and nb % args.log_every == 0:
                now = time.time()
                print(f"  epoch {epoch+1} batch {nb}/{len(loader)} loss {loss.item():.4f} "
                      f"({args.log_every/(now-last):.1f} it/s)", flush=True)
                last = now
        avg = total / max(1, nb)

        line = f"epoch {epoch+1}/{args.epochs} | train {avg:.4f} | {time.time()-start:.0f}s"
        if args.eval_every and (epoch + 1) % args.eval_every == 0:
            m = _quick_eval(model, dataset.samples, device, args.eval_max_len, args.eval_n)
            line += (f" | F1 {m['field_f1']:.3f} prod_rec {m['product_recall']:.3f} "
                     f"anls {m['anls']:.3f} valid {m['valid']:.2f}")
        print(line, flush=True)

        _save_checkpoint(ckpt_dir, model, optimizer, epoch + 1, avg)
        _prune_checkpoints(ckpt_dir, args.keep_last)

    print("Training done", flush=True)


if __name__ == "__main__":
    main()
