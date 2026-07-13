# worker-ocr-vlm-receipt

Worker OCR, backend **receipt-vlm-500m** — le VLM hybride maison
(CLIP ViT-B/16 gelé + projecteur entraîné + SmolLM2-360M + LoRA mergé),
inférence CPU, décodage contraint par grammaire → JSON canonique direct.

Un des 6 workers « un backend = un worker » issus de `dev_ocr`. Le pipeline
commun vit dans [`libs/pricetracker_receipt_pipeline`](../../libs/pricetracker_receipt_pipeline) ;
`receipt_vlm_provider.py` est propre à ce worker. Le **code du modèle** reste
dans `dev_ocr/vlm_training` (paquet `receipt_vlm`), consommé en lecture seule
via `[tool.uv.sources]` — même mécanisme que `workers/ocr-llm` avec `dev_ocr`.

## Flux

`Pub/Sub push (topic ocr-vlm-receipt)` → `POST /push` (OIDC) →
`tickets.gcs_path` → image GCS → `ReceiptVlmProvider` → `ReceiptParser`
(court-circuit : le modèle émet déjà le JSON canonique) → `alias_lookup` (EAN)
→ écriture atomique.

Réponses : `204` = ACK (succès **ou** échec déterministe), `400` = payload
malformé (ACK), `5xx` = erreur transitoire → NACK → retry → DLQ après 5 essais.

## Poids modèle

- **Checkpoint mergé** (~1,8 Go) : hors image, téléchargé depuis
  `PRT_MODEL_GCS_URI` au démarrage (`lifespan`) vers `PRT_MODEL_LOCAL_DIR`,
  puis `RECEIPT_VLM_MODEL_PATH` est posé. Échec = démarrage KO (Cloud Run
  relance ; aucun message ACKé par un worker sans poids).
- **Backbones HF** (CLIP + SmolLM2) : **baked dans l'image** au build
  (`HF_HOME=/opt/hf-cache`, `HF_HUB_OFFLINE=1`). `from_merged_checkpoint`
  appelle `from_pretrained` au chargement, or Cloud Run tourne en
  `PRIVATE_RANGES_ONLY` (pas d'egress internet public).

Prérequis ops (une fois) :

```bash
gsutil cp dev_ocr/vlm_training/checkpoints/receipt_vlm_500m_merged.pt \
  gs://price-tracker-prod-01-models/vlm/receipt-vlm/v1/
```

## Variables d'environnement

| Var | Défaut | Rôle |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | Projet GCP. |
| `PRT_OCR_ENGINE_LABEL` | `receipt-vlm-500m` | Écrit dans `tickets.ocr_engine` / `ocr_model`. |
| `PRT_MODEL_GCS_URI` | — | URI `gs://` du `.pt` mergé. |
| `PRT_MODEL_LOCAL_DIR` | `/tmp/models` | Destination du download (tmpfs → compté dans la RAM de l'instance). |
| `RECEIPT_VLM_MODE` | `transcribe` (lib) → **doit être `json`** | Le provider refuse tout autre mode au démarrage. |
| `HF_HOME` / `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` | posés dans l'image | Backbones en cache local. |
| `PRT_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` / `POOL_SIZE` | — / 5432 / `price_tracker` / `pt_app` / — / 4 | Cloud SQL. `PASSWORD` = secret `prt-prod-cloudsql-password`. |
| `PRT_OIDC_DISABLE` | `0` | `1` = bypass OIDC (dev local uniquement). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | — | Allowlist des appelants. |
| `PRT_LOG_LEVEL` | `INFO` | |

## Développement

```bash
uv sync          # installe torch CPU (~200 Mo) + transformers
uv run pytest    # le modèle n'est jamais chargé : provider/backend monkeypatchés
```

## Build

Depuis la **racine du monorepo** (build long : image multi-Go) :

```bash
docker build -f workers/ocr-vlm-receipt/Dockerfile -t worker-ocr-vlm-receipt:dev .
gcloud builds submit . --config=workers/ocr-vlm-receipt/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD) \
  --project=price-tracker-prod-01
```

Déploiement : bumper `worker_ocr_vlm_receipt_image_tag` dans
`infra/envs/prod/variables_ocr_backends.tf`, puis `terraform apply`.
Dimensionnement Cloud Run : 4 vCPU / 16 Gi (chargement du checkpoint + inférence
fp32 CPU), `max_instances = 2`.
