# worker-ocr-vlm-scratch

Worker OCR, backend **OCR-VLM entraîné from scratch** : encodeur CNN+transformer
et décodeur autorégressif écrits à la main (`torch.nn`), sans CLIP ni LLM
pré-entraîné. Le modèle décode directement une séquence de schéma linéarisé,
convertie en ticket canonique.

Un des 6 workers « un backend = un worker » issus de `dev_ocr`. Le pipeline
commun vit dans [`libs/pricetracker_receipt_pipeline`](../../libs/pricetracker_receipt_pipeline).
Contrairement aux autres backends VLM, il n'existait **aucun provider** dans
`receipt_ocr` pour ce modèle (il n'était appelé que par les scripts d'éval) :
`scratch_backend.py` est donc écrit ici, et implémente `OcrBackend` **en
direct** — pas de `VlmBackend`/`VlmProvider`, puisque le modèle n'a ni prompt,
ni modes, ni retries. La recette d'inférence reproduit
`dev_ocr/vlm_training/scripts/evaluate_ocr_vlm.py`.

Le **code du modèle** reste dans `dev_ocr/vlm_training` (paquet `receipt_vlm`),
consommé en lecture seule via `[tool.uv.sources]` — même mécanisme que
`workers/ocr-llm` avec `dev_ocr`.

## Flux

`Pub/Sub push (topic ocr-vlm-scratch)` → `POST /push` (OIDC) →
`tickets.gcs_path` → image GCS → `prepare_ocr_pixels` (letterbox 384×256) →
`OcrVLM.generate` (décodage glouton) → `Ticket.to_dict()` → JSON canonique →
`ReceiptParser` (court-circuit `try_parse_vlm_json`) → `alias_lookup` (EAN) →
écriture atomique.

Réponses : `204` = ACK (succès **ou** échec déterministe), `400` = payload
malformé (ACK), `5xx` = erreur transitoire → NACK → retry → DLQ après 5 essais.

## Poids modèle — DEUX fichiers

Hors image, téléchargés au démarrage (`lifespan`) :

| Env | Fichier | Env posée pour le backend |
|---|---|---|
| `PRT_MODEL_GCS_URI` | `ocr_vlm_epoch0XX_*.pt` | `RECEIPT_VLM_MODEL_PATH` |
| `PRT_TOKENIZER_GCS_URI` | `tokenizer_*.json` | `RECEIPT_VLM_TOKENIZER_PATH` |

Le déploiement par défaut pointe **epoch050** (Stage B) : sur données réelles
(WildReceipt), ANLS 0.183 vs 0.170 et `product_recall` doublé par rapport à
epoch040 (`dev_ocr/vlm_training/checkpoints/eval_epoch0*.json`). Le `loss` plus
élevé (0.3619) est celui du mix synthétique+réel, pas une régression.

Prérequis ops (une fois) :

```bash
gsutil cp dev_ocr/vlm_training/checkpoints/ocr_vlm_epoch050_loss0.3619.pt \
          dev_ocr/vlm_training/checkpoints/tokenizer_20260607_0900.json \
          gs://price-tracker-prod-01-models/vlm/ocr-vlm-scratch/v1/
```

## ⚠️ Ne jamais charger ce modèle en local

Le chargement + `generate` de ce modèle a déjà **figé la machine de dev**. Il
n'a été évalué que sur Kaggle. Les tests de ce worker **monkeypatchent** le
modèle : `uv run pytest` ne charge jamais le checkpoint. La première inférence
réelle a lieu sur Cloud Run.

## Variables d'environnement

| Var | Défaut | Rôle |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | Projet GCP. |
| `PRT_OCR_ENGINE_LABEL` | `ocr-vlm-scratch` | Écrit dans `tickets.ocr_engine` / `ocr_model`. |
| `PRT_MODEL_GCS_URI` | — | URI `gs://` du checkpoint `.pt`. |
| `PRT_TOKENIZER_GCS_URI` | — | URI `gs://` du `tokenizer.json`. |
| `PRT_MODEL_LOCAL_DIR` | `/tmp/models` | Destination des downloads. |
| `PRT_SCRATCH_MAX_LEN` | `0` (= défaut modèle, 640) | Plafond du décodage glouton. |
| `PRT_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` / `POOL_SIZE` | — / 5432 / `price_tracker` / `pt_app` / — / 4 | Cloud SQL. `PASSWORD` = secret `prt-prod-cloudsql-password`. |
| `PRT_OIDC_DISABLE` | `0` | `1` = bypass OIDC (dev local uniquement). |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` | — | Allowlist des appelants. |
| `PRT_LOG_LEVEL` | `INFO` | |

## Développement

```bash
uv sync          # installe torch CPU (~200 Mo)
uv run pytest    # le modèle n'est JAMAIS chargé (cf. avertissement ci-dessus)
```

## Build

Depuis la **racine du monorepo** :

```bash
docker build -f workers/ocr-vlm-scratch/Dockerfile -t worker-ocr-vlm-scratch:dev .
gcloud builds submit . --config=workers/ocr-vlm-scratch/cloudbuild.yaml \
  --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD) \
  --project=price-tracker-prod-01
```

Déploiement : bumper `worker_ocr_vlm_scratch_image_tag` dans
`infra/envs/prod/variables_ocr_backends.tf`, puis `terraform apply`.
Dimensionnement Cloud Run : 2 vCPU / 4 Gi, `max_instances = 2`.
