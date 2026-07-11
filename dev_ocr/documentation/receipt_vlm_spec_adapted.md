# French Receipt VLM — Adapted Specification (project-integrated)

> **Status**: adapted from the draft `receipt_vlm_spec.docx`. The draft was written as a
> *standalone* repository spec; this version re-anchors it to the actual `price-tracker`
> codebase so the hybrid pretrained/from-scratch VLM plugs into the existing
> `receipt_ocr` VLM backend instead of living in a parallel universe.
>
> **Goal**: a ~500M-parameter Vision-Language Model (frozen CLIP encoder + from-scratch
> multimodal projector + frozen SmolLM decoder with hand-rolled LoRA adapters) that reads a
> French supermarket receipt photo and emits the **project's canonical JSON schema**,
> exposed as a new `VlmProvider` selectable via `RECEIPT_VLM_MODEL`.

---

## 1. How this differs from the draft docx

The draft is technically sound as an academic LLaVA-style exercise, but it ignores the
existing codebase. The following adaptations are mandatory:

| # | Draft says | Adapted decision | Why |
|---|------------|------------------|-----|
| 1 | New standalone repo `receipt-vlm/` with its own schema | Training code lives in `dev_ocr/vlm_training/` (new top-level package `receipt_vlm`, **not** inside `src/receipt_ocr/`); inference plugs into `receipt_ocr.backends.vlm` as a new provider | `receipt_ocr` is consumed by `workers/ocr` in production — it must stay lightweight; training deps (torch, albumentations, datasets, accelerate) must never leak into the runtime package |
| 2 | Custom output schema (`store/date/time/items/subtotal_ht/tva_breakdown/total_ttc/payment/loyalty_points`) | Train directly on the **canonical schema** already enforced by `receipt_ocr.vlm_parse` / `constants.TicketField`: `{ticket: {date, chaine_supermarche, adresse, produits: [{nom_produit, prix_unitaire_ou_kg, unites}]}}`, date format `yyyyMMdd HH:mm` | Avoids a lossy mapping layer at inference; the existing parser, validator (`vlm_validate`) and retry loop in `backends/vlm/extraction.py` work unchanged. Rich fields (TVA, payment, SIRET) are out of scope for v1 — the downstream DB (`prix_extraits`) doesn't store them |
| 3 | SmolLM-1.7B decoder, `lang_dim=1024` in §2.2 but `2048` in §6, "~360M decoder", "~500M total" | **SmolLM-360M** (`HuggingFaceTB/SmolLM2-360M-Instruct`), `lang_dim=960` everywhere | The draft is internally inconsistent: SmolLM-1.7B is ~1.7B params (hidden 2048), which breaks the "~500M total" claim. SmolLM-360M (hidden **960**) gives ≈ 86M (CLIP) + 360M (LM) + ~15M (projector) + ~5M (LoRA) ≈ **466M** — matching the stated budget and fitting free Colab T4 |
| 4 | §1.2/§3 reference a trained "JSON schema decoder head" (`json_head.py`, ~5M params) but the spec never defines it (no §2.4) and `ReceiptVLM.forward` never uses it | **Drop the trained head.** Use *constrained JSON decoding at generation time* (grammar/regex-constrained sampling, e.g. `outlines` or a hand-rolled token-mask state machine — the latter still counts as a from-scratch contribution) | A trained head that re-projects logits cannot guarantee valid JSON anyway; constrained decoding does, deterministically, with zero trainable params. The existing `vlm_parse` + retry loop remains as a second safety net |
| 5 | Augmentation pipeline resizes to **448×448**, but CLIP ViT-B/16 with 197 tokens implies **224×224** | Resize to **224×224** (or swap to `clip-vit-base-patch16-384` and update `num_patches=577` consciously) | 448 input on ViT-B/16 yields 785 patches and breaks the frozen positional embeddings. Receipts are tall and narrow — reuse the existing `receipt_ocr.vlm_image_prep` crop (`RECEIPT_VLM_CROP=auto`) **before** the square resize to preserve legibility |
| 6 | CORD/SROIE as primary training data | Keep CORD/SROIE for **phase 1 only** (vision→language alignment, schema-mapped); phases 2–3 train on **synthetic French receipts + the project's real photos** in `dev_ocr/data/raw/images_tickets_caisse/` (+ `kaggle`, `huggingface`, `ocr_testing` subsets where relevant) | CORD is Korean, SROIE is English and both use different label schemas; they teach layout grounding, not French extraction. The repo already owns real French receipt photos — annotate them via the **Groq provider + manual review** (cheap pseudo-labelling) |
| 7 | Evaluation = field F1 / ANLS targets in a vacuum | Same metrics, but **benchmarked against the Groq `llama-4-scout` provider on an identical held-out set** of real French receipts, scored through the existing `vlm_validate` quality checks | Groq is the production baseline; the hybrid model only earns a registry slot if the gap is quantified |

Everything else in the draft (LoRA implementation §2.3, projector design §2.2, 3-phase
curriculum §5, synthetic generator §4.2, hand-rolled trainer §5.2) is kept as-is, modulo the
dimension fixes above.

---

## 2. Integration contract with `receipt_ocr` (the part the draft missed)

### 2.1 New provider

The runtime touchpoint is intentionally tiny — three files in `src/receipt_ocr`:

1. **`constants.py`** — add:

```python
class VlmModelName(str, Enum):
    MOONDREAM_0_5B = "moondream-0.5b"
    GROQ_LLAMA4_SCOUT = "groq-llama4-scout"
    RECEIPT_VLM_500M = "receipt-vlm-500m"   # NEW
```

2. **`backends/vlm/receipt_vlm_provider.py`** — new `VlmProvider` implementing the existing
   two-method interface (`model_id`, `analyze(image_path, prompt) -> str`):

```python
class ReceiptVlmProvider(VlmProvider):
    """Local inference for the hybrid CLIP+SmolLM receipt VLM.

    Loads a merged checkpoint (LoRA folded via ``LoRALinear.merge_weights``)
    from ``RECEIPT_VLM_MODEL_PATH``. Lazy-loads on first ``analyze`` call.
    Returns the raw JSON string; parsing/validation/retries stay in
    ``backends/vlm/extraction.py`` exactly as for Groq/Moondream.
    """
```

   - Checkpoint path resolved from the existing `ENV_VLM_MODEL_PATH` (`RECEIPT_VLM_MODEL_PATH`).
   - Image prep: reuse `vlm_image_prep` (crop → resize), then CLIP-normalize.
   - The `prompt` argument is accepted for interface compliance but the model was trained on a
     fixed instruction, so the provider may ignore or prepend it — document this in the docstring.
   - Inference deps (`torch`, `transformers`) declared as an **optional extra**:
     `pip install -e dev_ocr[receipt-vlm]` — never in the base install.

3. **`backends/vlm/registry.py`** — one new branch in `build_vlm_provider`.

Selection is then the standard mechanism, end to end:

```bash
RECEIPT_OCR_BACKEND=vlm
RECEIPT_VLM_MODEL=receipt-vlm-500m
RECEIPT_VLM_MODE=json                 # this model only supports JSON mode
RECEIPT_VLM_MODEL_PATH=/models/receipt_vlm_500m_merged.pt
```

`VlmMode.TRANSCRIBE` / `MULTIPASS` are not supported by this provider (it is trained
end-to-end for JSON emission); `analyze` should raise `OcrBackendError` if
`RECEIPT_VLM_MODE != json`, mirroring how mode handling already works in `extraction.py`.

### 2.2 Worker / production posture

- `workers/ocr` needs **zero code changes**: it already selects the engine via env vars and
  calls `receipt_ocr.extract_receipt`.
- Caveat: Cloud Run is CPU-only by default. A 466M model in int8 is runnable on CPU but slow
  (~tens of seconds/receipt). **Decision for v1: the hybrid VLM is a dev/eval engine and an
  academic deliverable; Groq remains the production default.** If it ever ships, options are
  Cloud Run GPU (L4) or a dedicated inference service — out of scope here.

---

## 3. Adapted repository layout

```
dev_ocr/
├── src/receipt_ocr/                      # runtime package (touched minimally, see §2.1)
│   └── backends/vlm/receipt_vlm_provider.py   # NEW — inference only
├── vlm_training/                         # NEW — everything below is training-side
│   ├── receipt_vlm/
│   │   ├── models/
│   │   │   ├── projector.py              # MultimodalProjector (from scratch, draft §2.2, lang_dim=960)
│   │   │   ├── lora.py                   # LoRALinear + inject_lora (from scratch, draft §2.3)
│   │   │   ├── constrained.py            # JSON-constrained decoding (replaces json_head.py)
│   │   │   └── vlm.py                    # ReceiptVLM assembly (draft §6, SmolLM-360M / 960-dim)
│   │   ├── data/
│   │   │   ├── schema.py                 # canonical-schema dataclasses + serializer (single source of truth = receipt_ocr.constants)
│   │   │   ├── synthetic.py              # French generator (draft §4.2) emitting CANONICAL labels
│   │   │   ├── augmentation.py           # draft §4.3 with 224×224 final resize
│   │   │   ├── cord_adapter.py           # CORD → canonical schema (phase 1 only)
│   │   │   ├── sroie_adapter.py          # SROIE → canonical schema (phase 1 only)
│   │   │   ├── real_photos.py            # loader for dev_ocr/data/raw/* + Groq pseudo-labels
│   │   │   └── dataset.py               # ReceiptDataset over all sources
│   │   ├── training/
│   │   │   └── trainer.py                # hand-rolled 3-phase loop (draft §5.2)
│   │   └── utils/metrics.py              # field F1, ANLS, price MAE
│   ├── scripts/
│   │   ├── pseudo_label.py               # run Groq provider over real photos → draft labels for manual review
│   │   ├── generate_synthetic.py
│   │   ├── train.py                      # --config configs/phaseN.yaml --resume ...
│   │   ├── evaluate.py                   # side-by-side vs Groq on held-out set
│   │   └── export_checkpoint.py          # merge LoRA, strip optimizer → single .pt for the provider
│   ├── configs/{base,phase1,phase2,phase3}.yaml
│   ├── requirements-training.txt         # torch, albumentations, datasets, accelerate, tensorboard...
│   └── README.md
└── data/raw/images_tickets_caisse/       # EXISTING real French photos → annotate & split
```

Notes:

- `vlm_training/` is its own installable package (or just a `pip install -r`-driven folder);
  it may **import** `receipt_ocr` (for constants/schema/image-prep reuse) but never the
  reverse, except for the single provider file which lazily imports torch.
- Checkpoints and datasets stay out of git (extend the existing `.gitignore`).

---

## 4. Model specification (corrected dimensions)

| Component | Status | Params | Notes vs draft |
|---|---|---|---|
| CLIP ViT-B/16 vision encoder (`openai/clip-vit-base-patch16`) | frozen pretrained | ~86M | input 224×224 → (B, 197, 768) |
| `MultimodalProjector` (cross-attn, 32 learned query tokens + residual MLP) | **from scratch** | ~12–15M | `vision_dim=768, lang_dim=960, num_patches=197` — draft code unchanged otherwise |
| SmolLM2-360M-Instruct decoder | frozen pretrained | ~360M | replaces SmolLM-1.7B; hidden 960 |
| LoRA adapters on every `q_proj`/`v_proj` (rank 16, α 32) | **from scratch** | ~4–8M | draft §2.3 verbatim, no `peft` |
| JSON-constrained decoder | **from scratch** (no params) | 0 | token-mask state machine over the canonical schema grammar; replaces the undefined `json_head.py` |
| **Total** | | **≈ 466M** | consistent with the "~500M" framing |

Training target: the canonical JSON serialized deterministically (sorted keys, fixed number
formatting `%.2f`, date `yyyyMMdd HH:mm`) so token-level cross-entropy is well-defined.
Labels shifted by the 32-token visual prefix (draft §8.4 pitfall — still applies).

---

## 5. Data plan (adapted)

| Source | Role | Labels | Notes |
|---|---|---|---|
| Synthetic French receipts (generator, draft §4.2) | phases 1–3, bulk volume (5–10k) | perfect, auto | generator must emit **canonical schema**; extend product/store lists; render variants (fonts, widths, missing fields) |
| CORD (`naver-clova-ix/cord-v2`) | phase 1 alignment only | mapped → canonical (lossy ok) | teaches layout grounding |
| SROIE | phase 1 alignment only | mapped → canonical | same |
| `dev_ocr/data/raw/images_tickets_caisse/` + other raw sets | phases 2–3 fine-tune + **entire held-out test set** | Groq pseudo-labels, manually reviewed (`scripts/pseudo_label.py`) | the test split must be hand-verified, never pseudo-labelled only |

Augmentations: draft §4.3 unchanged except final `Resize(224, 224)`; apply
`vlm_image_prep`-style receipt cropping before augmentation for real photos.

---

## 6. Training (kept from draft, with deltas)

3-phase curriculum unchanged (§5.1): projector-only warmup → projector+LoRA → low-LR JSON
alignment. Hand-rolled `ReceiptTrainer` (no HF `Trainer`) kept as the from-scratch training
contribution. Deltas:

- Mixed precision: prefer `bf16` where available; the smaller decoder makes free-tier T4
  (fp16 + grad checkpointing) comfortably feasible — revised estimate **~3–4h total on T4,
  <1h on A100**.
- Phase 3 validation metric = field F1 computed on **canonical** fields + the existing
  `vlm_validate` pass-rate (a sample "passes" if it would not trigger a retry in production).
- `export_checkpoint.py` merges LoRA (`LoRALinear.merge_weights`) and saves a single
  inference-ready `.pt` consumed by `ReceiptVlmProvider`.

---

## 7. Evaluation & acceptance

Held-out set: ≥30 real French receipt photos, hand-verified labels, never seen in training.

| Metric | Target | Baseline to beat/approach |
|---|---|---|
| Field F1 (canonical fields) | > 0.85 | Groq `llama-4-scout` on same set |
| Product-line recall | > 0.90 | idem |
| Price MAE | < 0.05 € | idem |
| Date exact match | > 0.90 | idem |
| `vlm_validate` pass-rate (no retry needed) | > 0.80 | idem |
| Valid JSON rate | 1.00 (guaranteed by constrained decoding) | — |

Deliverable: `scripts/evaluate.py` prints a side-by-side table (hybrid VLM vs Groq) — this is
both the academic result and the go/no-go signal for any production use.

---

## 8. Build order

1. `vlm_training/receipt_vlm/models/lora.py` — draft §2.3 verbatim + tests (shapes, zero-init delta, merge correctness).
2. `models/projector.py` — draft §2.2 with `lang_dim=960` + shape tests.
3. `models/vlm.py` — assembly on SmolLM2-360M; smoke-test a forward pass on CPU.
4. `data/schema.py` + `data/synthetic.py` — canonical-schema generator; visually verify 20 renders.
5. `data/augmentation.py` (224×224) + `data/dataset.py`.
6. `scripts/pseudo_label.py` — Groq pseudo-labelling of real photos; manual review pass; freeze train/val/test splits.
7. `data/cord_adapter.py` / `sroie_adapter.py` (phase-1 only mapping).
8. `training/trainer.py` + configs; run phase 1 → 2 → 3.
9. `models/constrained.py` — JSON-constrained decoding; wire into `ReceiptVLM.generate`.
10. `scripts/export_checkpoint.py` + `scripts/evaluate.py` (vs Groq).
11. **Last**: `src/receipt_ocr/backends/vlm/receipt_vlm_provider.py` + constants/registry entries + provider unit tests (mocked model) — the only runtime-package change.

---

## 9. Open decisions (to settle before coding)

1. **Decoder choice**: SmolLM2-360M (recommended, fits "~500M" and free GPUs) vs keeping
   SmolLM-1.7B (better French fluency, ~1.8B total, needs A100 and breaks the param story).
2. **Constrained decoding**: hand-rolled token-mask state machine (stronger "from scratch"
   narrative, more work) vs `outlines` library (faster, weaker academic claim).
3. **Pseudo-label budget**: how many real photos can be manually reviewed (drives test-set
   size and phase-3 quality).
4. **Production ambition**: dev/eval engine only (recommended v1) vs deploying behind
   `workers/ocr` with GPU — defer until evaluation numbers exist.
