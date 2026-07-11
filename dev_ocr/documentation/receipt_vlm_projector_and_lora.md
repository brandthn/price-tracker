# Receipt VLM — the trained parts: projector & LoRA

**Purpose:** where the two *from-scratch / trainable* components of `receipt-vlm-500m` live in the
codebase and what they look like. Everything else in the model — CLIP ViT-B/16 and SmolLM2-360M — is
**frozen**; the projector and the LoRA adapters are the only weights actually trained.

All paths are under `dev_ocr/vlm_training/receipt_vlm/models/`.

| Component | File | Class / functions | ~Params |
|-----------|------|-------------------|---------|
| Multimodal projector | `models/projector.py` | `MultimodalProjector` | ~7M |
| LoRA adapters | `models/lora.py` | `LoRALinear`, `inject_lora`, `merge_lora` | ~4M |
| Assembly | `models/vlm.py` | `ReceiptVLM` (wires both in) | — |

The trainer persists exactly these and nothing else — its checkpoint filter keeps keys starting with
`projector.` or containing `lora_A` / `lora_B` (`receipt_vlm/training/trainer.py`, `_is_adapter_key`),
which is why checkpoints are adapter-only (~45 MB).

---

## 1. The projector — `models/projector.py`

Class **`MultimodalProjector`**. It is the core from-scratch contribution: it maps frozen CLIP patch
embeddings into the SmolLM2 token-embedding space so the language model can "read" the image. Design
is a **Q-Former-lite** — learned query tokens cross-attend to the CLIP patches, plus a residual MLP
summary. No pretrained weights.

### Inputs / outputs
- **in:** `(B, num_patches, vision_dim)` = `(B, 197, 768)` from CLIP ViT-B/16 (196 patches + CLS).
- **out:** `(B, num_queries, lang_dim)` = `(B, 32, 960)` visual tokens in SmolLM2 embedding space.

### Submodules (`__init__`)
- `pos_embedding` — learnable positional encoding for the patches, `nn.Parameter (1, 197, 768)`.
- `query_tokens` — the learned visual summary tokens (cross-attention queries), `nn.Parameter (1, 32, 960)`.
- `cross_attn` — `nn.MultiheadAttention(embed_dim=960, num_heads=8, kdim=768, vdim=768, batch_first=True)`:
  language-space queries attend to vision keys/values.
- `mlp` — `Linear(768 → 1920) → GELU → Dropout → Linear(1920 → 960)`; patch-level projection,
  mean-pooled into a residual summary.
- `norm1`, `norm2` — `nn.LayerNorm(960)`.

### Forward (sketch)
```
vision_features += pos_embedding
queries   = query_tokens.expand(B, -1, -1)
attended  = norm1(cross_attn(query=queries, key=vision_features, value=vision_features))
summary   = mlp(vision_features).mean(dim=1, keepdim=True)   # residual patch summary
return      norm2(attended + summary)                        # (B, 32, 960)
```

Defaults: `vision_dim=768, lang_dim=960, num_patches=197, num_queries=32, num_heads=8, dropout=0.1`.

---

## 2. The LoRA adapters — `models/lora.py`

Hand-rolled Low-Rank Adaptation (Hu et al., 2021), **no `peft` dependency**. A `LoRALinear` wraps a
frozen `nn.Linear` and replaces `W·x` with:

```
W·x  +  (B · A)·x · (alpha / rank)
```

where `A` and `B` are the only trainable matrices and `W` stays frozen.

### `LoRALinear.__init__`
- `original` — the wrapped pretrained `nn.Linear`; its params are frozen (`requires_grad = False`).
- `lora_A` — `nn.Linear(d_in → rank, bias=False)`, init `N(0, 0.02)`.
- `lora_B` — `nn.Linear(rank → d_out, bias=False)`, init **zeros**.
- `dropout` — applied to the LoRA branch input.
- `scale = alpha / rank`.

Because `B` starts at zero, the adapter is an **exact identity at init** (adds nothing until trained).
Defaults: `rank=16, alpha=32.0, dropout=0.05`.

### Forward
```
original_out = original(x)
lora_out     = lora_B(lora_A(dropout(x)))
return         original_out + scale * lora_out
```

### Helper functions (same file)
- `inject_lora(model, rank, alpha, dropout, target_modules=("q_proj", "v_proj"))` — recursively
  replaces the named `nn.Linear` layers with `LoRALinear`. Mutates in place.
- `LoRALinear.merge_weights()` / `merge_lora(model)` — fold the LoRA delta back into the base weights
  (`W += scale · Bᵀ·Aᵀ`) and return a plain `nn.Linear`. Used by `scripts/export_checkpoint.py` so the
  runtime provider loads an adapter-free model with zero inference overhead.
- `count_trainable_params(model)` — total / trainable / frozen parameter report.

---

## 3. How they're assembled — `models/vlm.py`

In `ReceiptVLM.__init__`:
- CLIP vision encoder loaded and **frozen**.
- `self.projector = MultimodalProjector(...)` — instantiated as the trainable bridge.
- `self.lm = AutoModelForCausalLM.from_pretrained(SmolLM2-360M)`, **frozen**, then
  `inject_lora(self.lm, rank=lora_rank, alpha=..., target_modules=("q_proj", "v_proj"))` adds the LoRA
  adapters onto the attention query/value projections. `lora_rank=0` skips injection (used when loading
  a merged inference checkpoint).

So the trainable surface is: **the whole projector + the LoRA `A`/`B` matrices on `q_proj`/`v_proj`**.
At export, `merge_lora` folds the adapters away and `export_merged_state` writes the single
inference checkpoint consumed by `receipt_ocr` via `RECEIPT_VLM_MODEL_PATH`.

## References
- `dev_ocr/vlm_training/receipt_vlm/models/projector.py`
- `dev_ocr/vlm_training/receipt_vlm/models/lora.py`
- `dev_ocr/vlm_training/receipt_vlm/models/vlm.py` (assembly)
- `dev_ocr/vlm_training/receipt_vlm/training/trainer.py` (`_is_adapter_key` — what gets saved)
- Architecture overview: Entry 11 in `dev_ocr/documentation.md`
