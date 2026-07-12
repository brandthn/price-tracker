### Entry 20 — 2026-07-12 (UTC+2)

**Scope:** The hybrid `receipt-vlm-500m` finally has numbers. Root-caused the `is_offline_mode` crash
that had kept it out of every comparison, fixed the Kaggle notebook, and re-ran it alone. **It loses
to the 52×-smaller from-scratch model.** Docs updated; no library or worker code changed.

#### The crash was caused by its own fix

`scripts/evaluate_all_backends.py` was never at fault: `run_hybrid()` is correct and `--backends
hybrid` already existed. The bug lived in `notebooks/evaluate_all_backends_kaggle.ipynb`, whose
install cell installed **every** backend unconditionally. From the failing log:

```
transformers 5.0.0 requires huggingface-hub<2.0,>=1.3.0, but you have huggingface-hub 0.36.2
transformers 5.0.0 requires tokenizers<=0.23.0,>=0.22.0,  but you have tokenizers 0.20.3
```

Two installs destroyed each other:

1. `pip -U transformers` — added earlier *to fix* `is_offline_mode` — pulled **transformers 5.0.0**,
   too new for the `huggingface_hub` 0.36 that `paddleocr` holds down.
2. `moondream==0.0.6`, running **after** it, **downgraded `tokenizers` to 0.20.3** (the pin already
   flagged in Entry 11).

transformers 5 ended up installed but broken. The hybrid is the only backend that imports it — hence
the only one to fall.

#### Fix: install only what the selected backends need

The notebook now opens with a config cell that is the single source of truth:

```python
BACKENDS = ["hybrid"]      # installs and runs this backend only
```

The install cell is conditional on it: `paddleocr` only for `paddle`/`ppocrv4`, `groq` only for
`groq`, `moondream` only for `moondream`, plus an explicit coherent trio
(`transformers>=4.44,<5`, `tokenizers>=0.22,<=0.23`, `huggingface_hub>=0.30,<1.0`). `pip -U
transformers` is gone. A `hybrid`-only run therefore installs neither paddle nor moondream, and
nothing clobbers `huggingface_hub` or `tokenizers`.

Two guards were added: a hard failure if `hybrid` is selected without its checkpoint attached, and a
warning if `hybrid` is listed alongside paddle/moondream (which would re-create the conflict).

**Verified on Kaggle T4 (2026-07-12):** `transformers 4.57.6 | huggingface_hub 0.36.2 | tokenizers
0.22.2`, no `SKIPPED`, `cmp_hybrid.json` written. **7 min** for the hybrid alone, vs ~57 min for the
full suite.

#### The result — a clean negative

Same 18 French photos, same metrics as every other backend
(`checkpoints/evaluate-all-backends-kaggle_20260712.log`):

| Metric | *hybrid* (457 M) | **ocrvlm** (8.7 M) | groq |
|---|---|---|---|
| Read acc (1−CER) | **0.064** | 0.113 | 0.790 |
| Valid (non-empty) | 1.000 | 1.000 | 1.000 |
| Product recall | 0.000 | 0.000 | 0.682 |
| Field F1 | 0.000 | 0.000 | 0.746 |
| ANLS | **0.258** | 0.166 | 0.986 |
| Date exact match | 0.000 | 0.000 | 0.944 |

**The 457 M hybrid reads roughly half as well as the 8.73 M from-scratch model** (0.064 vs 0.113) —
despite being 52× larger and built on two pretrained backbones.

Its **higher ANLS (0.258 vs 0.166) is not a contradiction**: ANLS scores fields against gold and
rewards a plausible structure, while read-accuracy counts characters actually read. The hybrid emits
**well-formed tickets whose content is more wrong** — the constrained decoder guarantees the shape,
not the truth.

The likely cause is recorded plainly: the merged 1.82 GB artifact was exported from a **phase-2 /
epoch-4 checkpoint — phase 3 (JSON alignment) never ran** (Entry 14). Pretrained backbones do not
redeem an unfinished training run. This retroactively justifies the pivot to the smaller,
fully-owned architecture.

#### Docs updated

- `documentation/section_ocr_rapport.md` — §3.4a rewritten from "never evaluated / crashed" to
  "measured, and disappointing"; the §3.5 table gains a `hybride` column and a 3rd reading ("the
  bigger model is not the better one"); the old reading 3 becomes 4.
- `documentation/section_ocr_slides.md` — slide 1 row 5, slide 2 table + readings, speaker notes.

#### Still open

- **Nobody reads a date.** 0.000 for all three local models, including on *synthetic* data where the
  labels are perfect. Cross-model failure, still the highest-yield targeted fix.
- **Reading ≠ extraction.** All three local models score 0.000 on product recall and Field F1.
- The hybrid could be re-trained through phase 3 and re-measured — but on this evidence, effort is
  better spent on the from-scratch model, whose curve was still rising at the epoch cap.

#### References

- Fixed notebook: `vlm_training/notebooks/evaluate_all_backends_kaggle.ipynb`
- Run log: `vlm_training/checkpoints/evaluate-all-backends-kaggle_20260712.log`
- Harness (unchanged): `vlm_training/scripts/evaluate_all_backends.py`
- The dependency pin that started it: Entry 11 · the unfinished phase 3: Entry 14

---
