## Version 0.2.0 (unreleased)

### Entry 17 — 2026-07-07 (UTC+2)

**Scope:** Ran **Stage B** (real-data mixing) end-to-end and added a **read-accuracy** metric that
finally quantifies real-photo reading. Result: the from-scratch OCR-VLM's real read-accuracy nearly
**quadrupled** (0.033 → 0.122) with no synthetic regression — real-data mixing works, now measured.
Also: an on-GPU Kaggle eval notebook (local eval OOM'd a workstation).

#### Stage B run (Kaggle T4, schema, resumed epoch 40 → 50, real ×4 + synthetic)

`mixing 3500 real (x4) + 4000 synthetic`, 875 distinct real receipts (wildreceipt 804 + srd 71).
Synthetic held-out (trainer's own eval) *improved* across the 10 epochs (ANLS 0.904 → 0.940,
product_recall 0.558 → 0.760) — no catastrophic over-adaptation to the small real set. Checkpoint
`ocr_vlm_epoch050_loss0.3619.pt`.

#### Read-accuracy metric — `score()` / `_read_accuracy()` in `evaluate_ocr_vlm.py`

The field/ANLS metrics stayed at **0** on real even as the model visibly started reading, because they
exact-match-penalize near-reads and choke on WildReceipt's space-stripped gold + foreign currency.
New metric: concatenate a ticket's readable text (store + product names, in order), normalize to
lowercase alphanumerics (drops spaces/punct/currency), and score `1 − CER` — an order-preserving,
segmentation- and currency-agnostic "did the glyphs get read" signal. Validated: correct-text/wrong-price
→ 1.0, near-read → 0.93, hallucinated store → 0.0.

#### The verdict — real reading nearly quadrupled, synthetic held

| WildReceipt (424) | epoch 40 (synth-only) | epoch 50 (Stage B) |
|-------------------|----------------------:|-------------------:|
| **Read acc (1−CER)** | **0.033** | **0.122** (×3.7) |
| ANLS | 0.170 | 0.184 |
| Field F1 / product_recall | 0.000 / 0.001 | 0.000 / 0.002 |
| Synthetic Read acc | 0.486 | 0.451 |

Epoch 40 hallucinated synthetic stores on every real image (read_acc ≈ noise); epoch 50 attempts real
reads (`WAL[UNK]MART`, `BANANAS`). **Direction validated, magnitude still small** — 0.122 = ~12% of real
characters, not enough for exact field/product matches (F1 still 0). Price MAE 32.7 on WildReceipt is a
currency artifact (rupee gold vs EU-scale reads), not error.

#### On-GPU Kaggle eval (lesson: don't eval locally)

Autoregressive `generate` over 424 receipts × 2 checkpoints pegged a local workstation (near-freeze).
Moved eval to Kaggle T4: `notebooks/eval_ocr_vlm_kaggle.ipynb` (materialize bundle → auto-locate real
data + every `ocr_vlm_epoch*.pt` → run `evaluate_ocr_vlm.py` per checkpoint). Added `--data-dir`
(attached-dataset base) + recursive `_resolve_data_base` (Kaggle nests inputs under
`/kaggle/input/datasets/<slug>/`), and made a missing dataset **skip** instead of crash. Eval checkpoints
shipped as a separate `receipt-vlm-eval-ckpts` dataset (40 + 50 + tokenizer). WildReceipt eval ≈ 8–10 min
per checkpoint on T4.

Gotcha logged: notebook cells generated via a heredoc collapsed `\n` escapes into real newlines and
broke a string literal — generate notebook code with plain `print()` calls, no embedded escape sequences.

#### Still pending

- Push real read-accuracy up: more real data + more epochs, heavier synthetic augmentation
  (`--distort-intensity medium|heavy`), the pretrained-decoder reserve lever.
- A cleaner real yardstick: `trainingdatapro` (English/USD, real store names) is more interpretable than
  WildReceipt's mangled gold — add it to the uploaded eval data.
- Fix date reading (still 0.000 even on synthetic).
- Baseline comparison vs Groq + CLIP+SmolLM2 (Stage C proper).

#### References

- Eval harness + metric: `vlm_training/scripts/evaluate_ocr_vlm.py`
- Kaggle eval notebook: `vlm_training/notebooks/eval_ocr_vlm_kaggle.ipynb`
- Stage B trainer flags: `vlm_training/scripts/train_ocr_vlm.py` (`--real`/`--real-repeat`/`--real-data-dir`)
- Prior: Entry 16 / `documentation/entries/2026-07-06-ocr-vlm-m1-result-and-stage-b.md`
