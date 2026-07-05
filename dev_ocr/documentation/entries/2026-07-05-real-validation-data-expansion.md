## Version 0.2.0 (unreleased)

### Entry 15 — 2026-07-05 (UTC+2)

**Scope:** Expand the receipt VLM's **real validation data** from ~18 French-only photos to **1,875 labelled Latin-script receipts** across four public datasets, so a multilingual receipt OCR encoder (and the current model) can actually be measured. Adds a reusable `scripts/fetch_validation_data.py` + per-dataset adapters. No model/runtime change — data + tooling only.

#### Motivation

The held-out real set was 5 test receipts — too small and too French-only to trust any metric or to validate the planned multilingual/OCR-encoder direction (see the deployment/architecture discussion and `plans`). The fix is volume + language breadth from public receipt datasets, converted to the canonical `{"ticket": {...}}` schema so `scripts/evaluate.py` scores them unchanged.

#### What was landed (all under `dev_ocr/data/`)

| Dataset | Receipts | Split (train/val/test) | Method | Licence |
|---------|---------:|------------------------|--------|---------|
| CORD-v2 (`naver-clova-ix/cord-v2`) | 200 | — / 100 / 100 | `cord_adapter` (existing) | CC-BY (Indonesian, full line items) |
| TrainingDataPro OCR Receipts (HF) | 19 | — / 10 / 9 | **new** `trainingdatapro_adapter.py` | CC-BY-NC-ND-4.0 (non-commercial eval only) |
| ExpressExpense SRD | 128 | 71 / 19 / 38 | Groq `pseudo_label.py` (partial, see below) | MIT |
| **WildReceipt (OpenMMLab)** | **1,528** | 804 / 300 / 424 | **new** `wildreceipt_adapter.py` | research use (SDMGR/MMOCR) |
| **Total** | **1,875** | | | up from ~18 |

#### Key components

| Component | Path | Role |
|-----------|------|------|
| Fetch CLI | `vlm_training/scripts/fetch_validation_data.py` | `--datasets cord,sroie,trainingdatapro,srd_images,wildreceipt`; downloads + converts + writes canonical labels/splits/review under `data/raw/<name>` + `data/labels/<name>` |
| WildReceipt adapter | `vlm_training/receipt_vlm/data/wildreceipt_adapter.py` | maps 26 KIE classes → `Ticket`; Store/Addr/Date/Time value-classes → header fields; pairs each `Prod_item_value` box to its nearest `Prod_price_value` box on the same row (spatial y-pairing) → `produits` |
| TrainingDataPro adapter | `vlm_training/receipt_vlm/data/trainingdatapro_adapter.py` | parses CVAT `annotations.xml` boxes (shop/item/date_time text) → `Ticket` |

All adapters follow the existing `list[ReceiptSample]` convention (`receipt_vlm/data/dataset.py`); labels are `ticket.to_dict()` = `{"ticket": {...}}`, verified end-to-end through `load_real_samples`.

#### Routing insight (drove source selection)

Pseudo-labelling is the bottleneck: Groq's free tier is a **rolling 500k-token/day** window, and cleared only ~128 SRD receipts/day before throttling (retry rounds: 45 → 29 → 53 → 0 → 1). So **datasets that already ship transcribed text were preferred** (direct adapter, zero Groq) over box-only sets. WildReceipt (real per-box text + field classes, direct OpenMMLab download, **no account**) is why the 1000+ target was cleared cheaply; a box-only Roboflow set was deliberately skipped (would only re-hit the Groq wall).

#### Known limitations (per-source, don't treat as equally clean truth)

- **CORD**: Indonesian, IDR prices, no reliable store/address → strong for line-item/OCR-reading recall, weak for header fields / price-MAE-in-EUR.
- **WildReceipt**: annotation text is space-stripped (`JungleeHandtKukkad`) and dates parse ~54% (varied formats; unparseable left empty). Fine for `product_recall`/ANLS; store/address concatenate.
- **SRD**: 128/200 labelled (Groq quota); the other 72 images are on disk, resumable via `pseudo_label.py`. Pseudo-labels are provisional, not hand-reviewed.
- **Review status**: CORD/TrainingDataPro/WildReceipt are marked `reviewed=true` (dataset ground truth); SRD pseudo-labels are `reviewed=false`. `evaluate.py --split test` uses `require_reviewed=True`, so pass `require_reviewed=False` (or run `review_labels.py`) to score SRD.

#### How to use

```bash
# fetch/refresh any source (idempotent):
python scripts/fetch_validation_data.py --datasets wildreceipt
# evaluate a merged checkpoint on real receipts:
python scripts/evaluate.py --checkpoint <merged.pt> \
    --images ../data/raw/wildreceipt --labels ../data/labels/wildreceipt --split test
```

Raw images are `.gitignore`d per dataset (reproducible via the fetch script); small text labels are committable.

#### Still pending

- SRD remainder (72) — resume when Groq quota is fresher.
- Optional extra volume: Kaggle `dhiaznaidi/receiptdatasetssd300v2` (~2,901, CSV mirror has text → future `srd300_adapter.py`, no Groq). Roboflow skipped.
- Eval numbers vs Groq on this enlarged real set (still gated on a trained checkpoint) — future entry.

#### References

- Plan: `plans/…magical-feigenbaum.md` (Deliverable 0)
- Data loader / splits: `vlm_training/receipt_vlm/data/real_photos.py`
- Prior training-ops work: Entry 14 in this file
