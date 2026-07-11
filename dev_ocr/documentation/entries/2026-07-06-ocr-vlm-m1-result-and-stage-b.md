## Version 0.2.0 (unreleased)

### Entry 16 — 2026-07-06 (UTC+2)

**Scope:** First end-to-end result of the **from-scratch OCR-free VLM** (`OcrVLM`, no CLIP / no
SmolLM2). M1 (READ/STRUCTURE pretraining, schema target) finished on Kaggle T4; a new eval harness
measured it on real receipts and surfaced a **total sim-to-real gap**; **Stage B** (real-data mixing)
was implemented, tested, and wired into the Kaggle notebook. Model architecture unchanged — this entry
is about *measuring* M1 and *reacting* to it.

#### Motivation

M1 trained on **synthetic only** (on-the-fly multilingual receipts, perfect labels) — by design, to
teach the encoder+decoder to read at infinite variety/zero labelling cost. But `scripts/evaluate.py`
only runs the old CLIP+SmolLM2 model, so `OcrVLM` had **no eval path** and the 1,875 real receipts
(Entry 15) had never touched it. Before spending more GPU we needed to know: does the from-scratch
stack actually read *real* photos, or only its own synthetic distribution?

#### M1 training result (Kaggle T4, schema target, 40 epochs, ~5.6 h)

Synthetic held-out eval climbed monotonically and was **still rising at epoch 40** (stopped on the
epoch cap, not converged): `product_recall` 0.02 → **0.558**, ANLS 0.32 → **0.904**, `valid` JSON
**1.00** throughout; `field_f1` 0.148 (harsh exact-whole-field match — ANLS 0.90 = strings *nearly*
right, not yet char-perfect). Checkpoint `ocr_vlm_epoch040_loss0.2265.pt` + tokenizer live in Kaggle
Dataset `giorgiopasini/receipt-ocr-vlm-checkpoints`. Read: the from-scratch stack reads+structures
synthetic and just needed more steps.

#### New eval harness — `scripts/evaluate_ocr_vlm.py`

Drives the from-scratch stack (`OcrVLM.from_checkpoint` → `prepare_ocr_pixels` → greedy `generate` →
`Ticket`), scored by the shared `evaluate_tickets`. Prints a **per-dataset + aggregate** acceptance
table plus qualitative pred-vs-gold dumps; `--synthetic N` adds a held-out synthetic sanity column.
Reuses `load_real_samples` (handles WildReceipt's nested tree, enforces `reviewed` on test). Unlike
`evaluate.py` it needs no CLIP normalization / constrained decoding.

Reviewed real **test** available: cord 100 + wildreceipt 424 + trainingdatapro 9 = **533** (SRD's 39
are unreviewed pseudo-labels → excluded unless `--include-unreviewed`).

#### The finding — total sim-to-real gap (epoch-40 checkpoint)

| Metric | Synthetic (128) | WildReceipt (424) | TrainingDataPro (9) |
|--------|----------------:|------------------:|--------------------:|
| Field F1 | 0.078 | **0.000** | 0.000 |
| Product recall | 0.357 | **0.001** | 0.000 |
| ANLS | 0.787 | **0.170** | 0.185 |

The model reads its **synthetic** domain but **fails entirely on real photos** — and not by garbling:
on every real image it emits a *valid, coherent* ticket from a handful of **memorized synthetic
stores** (Lidl/Aldi/Carrefour/Conad) with French/Italian products. Examples: real "Jungle Jamboree" →
`Carrefour Express`; real "CVS/pharmacy" → `Lidl`; real "Trader Joe's" → `Lidl`. It generates from its
synthetic prior and barely conditions on real pixels. **Not a pipeline bug** — output structure is
always valid and real/synthetic share identical preprocessing. This is the #1 risk the plan flagged.
Secondary: **date reading is broken even on synthetic** (date_accuracy 0.000 — plausible-but-wrong
dates); CORD is unusable for this EU model (empty store/date, IDR prices) and WildReceipt gold is a
harsh yardstick (space-stripped OCR names), but the store-name miss on real is unambiguous.

Consequence: **more synthetic-only epochs won't help** (they'd just sharpen the synthetic prior). The
model must *see real receipts*.

#### Stage B — real-data mixing (implemented + wired, ready to run)

`scripts/train_ocr_vlm.py` gained `--real` / `--real-repeat` / `--real-data-dir`:
`build_real_train_samples()` loads the real **train** splits that exist (wildreceipt 804 + srd 71 =
**875**), oversamples them (`--real-repeat`, default 4) and mixes them into the synthetic stream.
Schema target only (real photos have no rendered transcription — guarded); auto-resume from epoch 40
still applies. Mixed batches work because `dataset._load_image` already handles both a real `Path` and
a synthetic callable. `--real-data-dir` overrides the data base so the same code runs locally or from
an attached Kaggle Dataset (`raw/<name>` + `labels/<name>`).

`notebooks/train_ocr_vlm_kaggle.ipynb` retargeted to Stage B (schema, N=4000, EPOCHS=50 → 10 more
epochs, REAL ×4, `REAL_DATA_DIR=/kaggle/input/receipt-vlm-real-data`). Real data zipped to
`colab_upload/receipt_vlm_real_data.zip` (195 MB, wildreceipt+srd raw+labels) for upload as Kaggle
Dataset `receipt-vlm-real-data`. Code bundle rebuilt with the new trainer + eval script.

#### How to use

```bash
# measure any OcrVLM checkpoint on real + held-out synthetic (run locally on GPU):
python scripts/evaluate_ocr_vlm.py \
    --checkpoint checkpoints/ocr_vlm_epoch040_loss0.2265.pt \
    --datasets cord_v2 wildreceipt trainingdatapro --synthetic 128

# Stage B locally (real data already on disk):
python scripts/train_ocr_vlm.py --target schema --n 4000 --real --real-repeat 4 \
    --checkpoint-dir checkpoints --distort
```

Kaggle Stage B: upload the two zips (code bundle new version + `receipt-vlm-real-data`), Add Input all
three datasets (code, `receipt-ocr-vlm-checkpoints`, `receipt-vlm-real-data`), Run All → resumes at
epoch 41 and pushes checkpoints per epoch.

#### Still pending

- Run Stage B; re-eval with `evaluate_ocr_vlm.py` — the number that matters is whether **WildReceipt
  store-F1 / ANLS moves off zero**. Watch the opposite failure too: over-adapting to 875 real receipts
  and losing synthetic ANLS.
- If the gap barely moves: heavier synthetic augmentation (`--distort-intensity medium|heavy`), more
  real diversity, and the plan's reserve lever (pretrained-decoder init).
- Fix date reading (broken even on synthetic).
- Baseline comparison vs Groq + CLIP+SmolLM2 once real metrics are non-trivial (Stage C proper).

#### References

- Eval harness: `vlm_training/scripts/evaluate_ocr_vlm.py`; trainer: `vlm_training/scripts/train_ocr_vlm.py`
- Model: `vlm_training/receipt_vlm/models/{ocr_encoder,ocr_decoder,ocr_vlm}.py`
- Plan: `plans/taking-into-consideration-the-magical-feigenbaum.md` (M1/M2 sections)
- Real data: Entry 15 / `documentation/entries/2026-07-05-real-validation-data-expansion.md`
