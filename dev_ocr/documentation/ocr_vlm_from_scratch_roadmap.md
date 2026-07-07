# From-scratch OCR-VLM — roadmap & how to resume

Living roadmap for the from-scratch, OCR-free receipt VLM (`OcrVLM`: hand-rolled CNN+transformer
encoder → autoregressive decoder → linearized schema → `Ticket`; no CLIP, no SmolLM2). Full history is
in `documentation.md` Entries 16–17; this file is the **resume-from-here** summary + prioritized next
steps. Update it whenever a step lands.

_Last updated: 2026-07-07._

## Where we are

| Milestone | Status | Evidence |
|---|---|---|
| M0 — PoC pipeline | ✅ | 8-receipt overfit → char-perfect reproduction (loss 4.0→0.096) |
| M1 — READ (synthetic, schema target) | ✅ | 40 epochs Kaggle T4; synthetic ANLS 0.32→0.90, product_recall 0.02→0.56 |
| Stage B — real-data mixing | ✅ | resumed 40→50 with 875 real receipts ×4; **real WildReceipt read_acc 0.033→0.122 (×3.7)**, synthetic held |
| M2 — structure + full eval | ◐ in progress | eval harness + read_acc metric done; real accuracy still low |
| M3 — scale / iterate | ☐ | not started |

**Current best checkpoint:** `ocr_vlm_epoch050_loss0.3619.pt` (Stage B). ~8.7M params, 384×256 input,
embed_dim 256, enc/dec depth 4, heads 8, max_len 768, vocab 190 (char tokenizer).

**Verdict:** the model went from hallucinating its synthetic prior on real photos (read_acc ≈ 0) to
genuinely *attempting* to read them (≈12% char accuracy). Direction proven; magnitude still small.

## Assets to resume with

- **Model code:** `receipt_vlm/models/{ocr_encoder,ocr_decoder,ocr_vlm}.py`,
  `receipt_vlm/data/{ocr_transform,ocr_dataset,lin_schema,tokenizer}.py`.
- **Trainer:** `scripts/train_ocr_vlm.py` — resumable (per-epoch `ocr_vlm_epoch{NN}_loss{L}.pt`,
  auto-resume from latest, fixed `tokenizer.json`, `--keep-last` prune). Flags:
  `--target schema`, `--real --real-repeat N --real-data-dir <base>`, `--distort --distort-intensity`,
  `--n` (synthetic/epoch), `--epochs`, `--languages`.
- **Eval:** `scripts/evaluate_ocr_vlm.py` — `read_acc` (1−CER over concatenated readable text,
  currency/format-agnostic) + field/ANLS/product_recall; `--data-dir`, `--datasets`, `--synthetic N`.
  **Run eval on Kaggle, not locally** (autoregressive `generate` over hundreds of receipts froze a
  workstation).
- **Notebooks:** `notebooks/train_ocr_vlm_kaggle.ipynb` (Stage B), `notebooks/eval_ocr_vlm_kaggle.ipynb`
  (GPU eval, before/after over every attached checkpoint).
- **Kaggle datasets:** `receipt-ocr-vlm-checkpoints` (training checkpoints, versioned per epoch),
  `receipt-vlm-real-data-1640` (`raw/<name>`+`labels/<name>`), `receipt-vlm-eval-ckpts` (eval snapshots).
- **Real data on disk:** `data/raw/<name>` + `data/labels/<name>` for wildreceipt/cord/srd/trainingdatapro
  (train 875 = wildreceipt 804 + srd 71; reviewed test 533).

## Next steps (prioritized)

### 1. Scale real data + more Stage-B epochs — biggest lever
875 distinct real receipts (×4) over 10 epochs isn't enough. **How:** re-run
`train_ocr_vlm_kaggle.ipynb` with a bigger `EPOCHS` (e.g. 80) and, ideally, more real receipts folded
into the `receipt-vlm-real-data` dataset (label more SRD via `pseudo_label.py`; add more English/EU
public receipts). Trainer auto-resumes from the latest checkpoint — just attach the checkpoints dataset
and raise `EPOCHS`. Re-eval with `eval_ocr_vlm_kaggle.ipynb`; success = real `read_acc` keeps climbing
without synthetic `read_acc` collapsing.

### 2. Heavier synthetic augmentation
Shrink the sim-to-real gap by widening the synthetic visual distribution: set
`--distort-intensity medium` (then `heavy`) in the train notebook (`INTENSITY`). Watch that synthetic
metrics don't crater (too-hard synth can stall learning).

### 3. Cleaner real yardstick
WildReceipt gold is space-stripped OCR (`JalpartFishTikka`) + foreign currency — it understates
progress. Add `trainingdatapro` (English/USD, real store names) and report **per-source** `read_acc`.
This is a small change to the eval data/notebook, not the model.

### 4. Fix date reading
`date_accuracy` is **0.000 even on synthetic** — the decoder emits plausible-but-wrong dates. Inspect
how dates are rendered vs. encoded in the schema target (`lin_schema.ticket_to_linear`, the `[DATE]`
field) and whether the date format is learnable char-by-char. Likely a targeted fix worth outsized gain.

### 5. Pretrained-decoder reserve lever (only if 1–4 stall)
Donut inits its decoder from mBART. If from-scratch decoding plateaus on open-vocab product names,
initialize the decoder from a tiny pretrained multilingual LM. Biggest single quality lever held in
reserve; breaks the "fully from-scratch" purity, so use only if needed.

### 6. Stage C — integrate into the worker (deferred)
Once real accuracy is useful, wire `OcrVLM` behind the `receipt_ocr` backend interface (a provider like
`receipt_vlm_provider.py`) so it's selectable via `RECEIPT_OCR_BACKEND`. Not worth doing until the
numbers justify it.

## How the multi-backend comparison relates

`scripts/evaluate_all_backends.py` + `notebooks/evaluate_all_backends_kaggle.ipynb` compare this model
against Paddle / PP-OCRv4 / hybrid CLIP+SmolLM2 / Groq / Moondream on the French real photos. Use it to
track where the from-scratch model sits versus the alternatives as steps 1–4 land.
