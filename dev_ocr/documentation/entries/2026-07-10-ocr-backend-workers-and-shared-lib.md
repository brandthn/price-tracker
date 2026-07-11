### Entry 18 — 2026-07-10 (UTC+2)

**Scope:** Productionization of every `receipt_ocr` backend as its **own Cloud Run worker**
(`workers/ocr-paddle`, `ocr-ppocrv4`, `ocr-vlm-moondream`, `ocr-vlm-groq`, `ocr-vlm-receipt`,
`ocr-vlm-scratch`), with the shared pipeline extracted into a new monorepo library
`libs/pricetracker_receipt_pipeline`. **No file under `dev_ocr/` was modified** — only this
documentation. `dev_ocr` remains the research source of truth.

#### Motivation

`dev_ocr` proved that backends are interchangeable behind one parser (Strategy pattern), but only
two of them ever reached production, and both through a single worker: `workers/ocr` (tier-1, Groq)
and `workers/ocr-llm` (tier-2, Gemini). Comparing engines on real traffic meant flipping env vars on
a shared service. Splitting into one worker per backend makes each engine independently deployable,
resourced and measurable — publish the same `ticket_id` on two topics, compare the rows written.

#### What was created

| Artifact | Path | Role |
|---|---|---|
| Shared library | `libs/pricetracker_receipt_pipeline` | Frozen copy of the pipeline + the worker runtime |
| Worker (Paddle) | `workers/ocr-paddle` | `PaddleOcrBackend`, models baked into the image |
| Worker (PP-OCRv4) | `workers/ocr-ppocrv4` | `PpOcrV4MobileBackend` (+ its `paddle_backend` wrapee) |
| Worker (Moondream) | `workers/ocr-vlm-moondream` | `MoondreamProvider`, `.mf` weights from GCS |
| Worker (Groq) | `workers/ocr-vlm-groq` | `GroqProvider`, `GROQ_API_KEY` via Secret Manager |
| Worker (receipt-vlm-500m) | `workers/ocr-vlm-receipt` | `ReceiptVlmProvider`, merged `.pt` from GCS |
| Worker (from-scratch) | `workers/ocr-vlm-scratch` | **New** `OcrVlmScratchBackend` (see below) |
| Terraform | `infra/envs/prod/*_ocr_backends.tf` | 6 services, 6 topics + DLQs, 6 push subscriptions |

`tesseract` and `easyocr` were skipped: both are still `NotImplementedError` stubs.

#### The library split

`libs/pricetracker_receipt_pipeline` holds exactly what more than one worker needs, in two layers:

- **Pipeline layer** — copied verbatim from `src/receipt_ocr/` with imports rewritten
  (`receipt_ocr.` → `pricetracker_receipt_pipeline.`): `parser.py`, `constants.py`, `exceptions.py`,
  `image_utils.py`, `vlm_parse.py`, `vlm_validate.py`, `vlm_image_prep.py`, `vlm_text_cleanup.py`,
  `backends/base.py`, `backends/vlm/{base,extraction,multipass,prompts}.py`.
- **Worker runtime** (`worker/`) — lifted from `workers/ocr-llm`: OIDC auth, structlog JSON logging,
  GCS download, Pub/Sub envelope parsing, the atomic Cloud SQL write, the schema→SQL mapper, plus a
  new `weights.py` (idempotent GCS model download at startup).

Concrete backends and providers are **not** in the library. Each worker copies the one it uses, so
`paddlepaddle` never ships in the Groq image and `torch` never ships in the Paddle image.

**Two adaptations were required** (the only behavioural deltas vs `dev_ocr`):

| `dev_ocr` | Library | Why |
|---|---|---|
| `VlmBackend(provider=None, model=None, **kw)` → falls back to `build_vlm_provider()` | `VlmBackend(provider)` — required arg | No registry: each worker hardwires one backend |
| `auth.verify_oidc` reads a module-level `get_settings()` | `build_verify_oidc(get_settings)` factory | The library must not own a settings singleton |

**Deliberately not copied:** `extract_receipt.py` and `backends/vlm/registry.py` (factories — dead
weight when the backend is fixed at build time), `env.py` (`.env` loading, replaced by
pydantic-settings), the two stubs.

#### The from-scratch OCR-VLM had no provider

`OcrVLM` (Entries 16–17) lived only in `vlm_training/` and was reachable solely through
`scripts/evaluate_ocr_vlm.py` — there was no `receipt_ocr` provider for it. `workers/ocr-vlm-scratch`
therefore introduces `scratch_backend.py`, which implements `OcrBackend` **directly** rather than
going through `VlmBackend` / `VlmProvider`. That machinery exists for prompts, crop escalation and
validation-driven retries; this model has none of them — it takes no prompt and decodes the canonical
ticket deterministically. Inference mirrors the eval script:

```text
CharTokenizer.load(tokenizer.json)
  → OcrVLM.from_checkpoint(ckpt.pt, tokenizer, device="cpu")
  → prepare_ocr_pixels(image)            # letterbox 384×256, CHW float32
  → model.generate(batch)                # greedy, ≤640 char tokens
  → Ticket.to_dict()  →  json.dumps
```

The emitted JSON is already the canonical schema, so `ReceiptParser.parse_text` short-circuits
through `try_parse_vlm_json` and the heuristic parser never runs — the same path Groq and
receipt-vlm-500m take. It is the only backend needing **two** weight files (checkpoint + character
tokenizer), which is why the worker config grew `PRT_TOKENIZER_GCS_URI` alongside
`PRT_MODEL_GCS_URI`.

**Deployed checkpoint: `ocr_vlm_epoch050_loss0.3619.pt`** (Stage B), per `eval_epoch0*.json`: real
ANLS 0.183 vs 0.170 and `product_recall` doubled vs epoch040. The higher loss is the synthetic+real
mix, not a regression. Consistent with the roadmap's "current best checkpoint".

> ⚠️ Per Entry 17, loading and generating with this model **froze a local workstation**. Its worker
> tests monkeypatch the model; the checkpoint is never loaded locally. The test that exercises
> `extract_text` asserts the real `prepare_ocr_pixels` preprocessing yields a `(1, 3, 384, 256)`
> batch against a stub model. First real inference happens on Cloud Run.

#### Worker contract (identical for all six)

Same contract as `workers/ocr` / `workers/ocr-llm` — see
[`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md):

```text
Pub/Sub push {"ticket_id": "..."}  →  POST /push (OIDC)
  → SELECT gcs_path FROM tickets
  → download image from GCS bronze
  → backend.extract_text() → ReceiptParser → canonical dict
  → alias_lookup.resolve_line_eans()   (pricetracker_matching, read-only)
  → atomic tx: DELETE prix_extraits → INSERT → UPDATE tickets (ocr_attempts bumped last)
  → HTTP 204
```

| Situation | HTTP | Effect |
|---|---|---|
| Success | 204 | ACK; rows written |
| Malformed Pub/Sub envelope | 400 | ACK |
| Deterministic failure (unreadable image, invalid model output) | 204 | ACK, no retry; previous result untouched |
| Transient failure (DB, GCS 5xx, weights unreachable) | 5xx | NACK → backoff → DLQ after 5 attempts |

`GET /healthz` answers only once the lifespan completed: weights downloaded, backend constructed, PG
pool up. A worker that cannot load its model therefore never ACKs a message — Cloud Run restarts it.

#### Model weights

Local-weight backends do **not** bake weights into the image; `worker/weights.py` downloads them from
the existing models bucket on cold start (download to `<file>.part` then `os.replace`, skipped when
the local file already matches the blob size).

| Worker | `PRT_MODEL_GCS_URI` (under `gs://<project>-models/`) |
|---|---|
| `ocr-vlm-moondream` | `vlm/moondream/v1/moondream-0_5b-int8.mf` |
| `ocr-vlm-receipt` | `vlm/receipt-vlm/v1/receipt_vlm_500m_merged.pt` |
| `ocr-vlm-scratch` | `vlm/ocr-vlm-scratch/v1/ocr_vlm_epoch050_loss0.3619.pt` (+ `tokenizer_20260607_0900.json`) |

Exception: `ocr-vlm-receipt` **bakes the HF backbones** (CLIP ViT-B/16, SmolLM2-360M-Instruct) into
the image with `HF_HUB_OFFLINE=1`, because `ReceiptVLM.from_merged_checkpoint` calls `from_pretrained`
at load time and Cloud Run runs with `vpc_egress = PRIVATE_RANGES_ONLY` (no public internet egress).
Paddle/PP-OCRv4 likewise bake their detection/recognition models at build time.

#### Sizing

| Worker | cpu / memory / max_instances | Rationale |
|---|---|---|
| `ocr-paddle`, `ocr-ppocrv4` | 2 / 4Gi / 3 | Local CPU inference + baked models |
| `ocr-vlm-moondream` | 2 / 2Gi / 3 | int8 0.5B weights in `/tmp` (tmpfs = RAM) |
| `ocr-vlm-groq` | 1 / 1Gi / 3 | No local inference; waits on the Groq API |
| `ocr-vlm-receipt` | 4 / 16Gi / 2 | 1.8 GB checkpoint in tmpfs + fp32 CPU load peak; >8Gi requires ≥4 vCPU |
| `ocr-vlm-scratch` | 2 / 4Gi / 2 | Compact model, but greedy decode ≤640 tokens on CPU |

`timeout_seconds = 540` everywhere, below the subscriptions' `ack_deadline_seconds = 600`.

#### This supersedes the GPU deployment plan

[`receipt_vlm_gcp_deployment_plan.md`](../receipt_vlm_gcp_deployment_plan.md) (2026-06-18) proposed
running `receipt-vlm-500m` **inside** `prt-prod-worker-ocr`, on an **NVIDIA L4 GPU**, behind a
Terraform `ocr_vlm_enabled` toggle. What shipped is the alternative that document itself recorded as
"considered": a **separate service per backend**, on **CPU**, no toggle. The existing Groq path is
untouched, each engine scales and fails independently, and no GPU quota is needed. The tradeoff is
accepted latency: fp32 CPU inference for `receipt-vlm-500m`, bounded by the 540 s worker timeout and
capped at 2 instances.

#### Infrastructure — additive only

Four new files in `infra/envs/prod/`; **no existing `.tf` file was modified**:

- `variables_ocr_backends.tf` — 6 image tags (default `skeleton` = the hello image, so `apply` works
  before the first build) + 4 model-URI variables.
- `cloud_run_ocr_backends.tf` — 6 services + a **separate** `ocr_backend_worker_sa_invoker` resource
  (adding keys to the existing `worker_sa_invoker` `for_each` would have re-planned the 6 live ones).
- `pubsub_ocr_backends.tf` — a **second instantiation** of `modules/pubsub` (it only creates
  per-topic resources, so it is safe to instantiate twice) with one topic + DLQ per backend. The
  `ticket-uploaded` and `ocr-retry` routings are byte-identical.
- `subscriptions_ocr_backends.tf` — 6 push subscriptions cloning `ocr_retry_worker_push` semantics.

The single edit to an existing file is an **append** to the root `.gcloudignore`, excluding
`dev_ocr/vlm_training/{checkpoints,colab_upload,data,notebooks}/` — 4.4 GB that was being uploaded
into the build context of *every* `gcloud builds submit`, including `ocr-llm`'s. Nothing reads those
directories at build time; the inference weights travel through the models bucket.

#### Verification

65 unit tests green (28 library + 5/5/5/5/7/10 per worker); all six FastAPI apps import and expose
`/healthz` + `/push`; `terraform validate` passes. No heavy model is loaded by any test — backends
are monkeypatched, so `torch`, `paddlepaddle` and the real checkpoints stay out of the test path.

```bash
cd libs/pricetracker_receipt_pipeline && uv run pytest
cd workers/ocr-vlm-groq && uv run pytest
docker build -f workers/ocr-vlm-groq/Dockerfile -t worker-ocr-vlm-groq:dev .   # from monorepo root
```

`terraform plan` (must show only `+ create`), the image builds, the weights upload and `apply` are
the devops team's steps; each worker's `README.md` and `cloudbuild.yaml` header carries the exact
commands.

#### Impact on `dev_ocr`

None, by design. The library is a **frozen copy**, not an import of `receipt_ocr`: `dev_ocr` stays
free to evolve (new backends, parser tweaks) without a Cloud Run rollout, and the workers stay
pinned to a reviewed snapshot. The cost is that a parser fix must be **ported** to
`libs/pricetracker_receipt_pipeline` to reach production — port it there, re-run both test suites.

Note that `workers/ocr` and `workers/ocr-llm` still consume `dev_ocr` directly through
`[tool.uv.sources] receipt-ocr = { path = "../../dev_ocr" }`, and `ocr-vlm-receipt` /
`ocr-vlm-scratch` consume `dev_ocr/vlm_training` the same way (read-only, model code only).

#### References

- Worker contract: [`workers/ocr/ocr-worker-contract.md`](../../../workers/ocr/ocr-worker-contract.md)
- Library: [`libs/pricetracker_receipt_pipeline/README.md`](../../../libs/pricetracker_receipt_pipeline/README.md)
- Superseded plan: [`receipt_vlm_gcp_deployment_plan.md`](../receipt_vlm_gcp_deployment_plan.md)
- From-scratch model: Entries 16–17 in this file, [`ocr_vlm_from_scratch_roadmap.md`](../ocr_vlm_from_scratch_roadmap.md)
- Template worker: `workers/ocr-llm/`

---
