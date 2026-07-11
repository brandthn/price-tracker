# Worker OCR — Contrat d'intégration

Document de référence pour le développeur du worker `prt-prod-worker-ocr`.
Cible : ce que le worker DOIT respecter pour s'intégrer au backend, à la DB
et au reste du data-plane PriceTracker tel que déployé (Phase 6.5).

Statut de l'infra autour de l'OCR :

- `prt-prod-worker-ocr` (Cloud Run) → skeleton `hello` déployé, **prêt à recevoir l'image OCR**
- Topic Pub/Sub `ticket-uploaded` → alimenté par GCS notification (`tickets/raw/` sur bucket bronze)
- Push subscription `ticket-uploaded-ocr-push` → pointe `${run_worker_ocr.uri}/push`, OIDC, DLQ à 5 échecs
- Cloud SQL `prt-prod-sql-main` + pgvector → table `products` (dim 768) déjà populée par worker OFF
- Tables `tickets` / `prix_extraits` → **n'existent pas encore** (Phase 7 backend, Alembic). Le contrat ci-dessous spécifie le schéma cible que le backend devra créer.

---

## 1. Périmètre

**In scope** :

1. Recevoir un événement `ticket-uploaded` (Pub/Sub push).
2. Télécharger l'image depuis GCS bronze.
3. OCR + parsing structuré (enseigne, date, lignes articles, total).
4. Résolution EAN par ligne (embedding Vertex + pgvector + fallback fuzzy) (DO NOT IMPLEMENT THIS YET, GO DIRECTLY TO STEP 5 USING NULL AS EAN)
5. Écrire le résultat en Cloud SQL (`tickets` UPDATE, `prix_extraits` INSERT, `product_aliases` candidates).

**Out of scope** (explicitement délégué) :

- ❌ Enrichissement catalogue (`products`, `catalogue_produits`) → **worker OFF**. L'OCR signale les EAN nouveaux ; OFF les pickera (cf. §8).
- ❌ Calcul d'indices → **worker Indices**.
- ❌ Envoi de notifications → **worker Alertes**.
- ❌ Génération de Signed URL d'upload → **backend FastAPI**.
- ❌ Création de la ligne `tickets` initiale → **backend** (statut `pending` au moment où il signe l'URL d'upload).

---

## 2. Trigger & contrat HTTP

Le worker est invoqué par **Pub/Sub push** sur la subscription `ticket-uploaded-ocr-push` (cf. [infra/envs/prod/subscriptions.tf](../infra/envs/prod/subscriptions.tf)).

### Endpoints exposés


| Méthode | Path       | Auth | Rôle                                        |
| ------- | ---------- | ---- | ------------------------------------------- |
| GET     | `/healthz` | none | Liveness Cloud Run                          |
| POST    | `/push`    | OIDC | Handler Pub/Sub push (1 message = 1 ticket) |


**Aucun autre endpoint.** Pas de `/run`, pas d'API métier — c'est event-driven only.

### Payload entrant (Pub/Sub push, JSON_API_V1)

```json
{
  "message": {
    "attributes": { "eventType": "OBJECT_FINALIZE", "bucketId": "...", "objectId": "tickets/raw/{user_id}/{uuid}.jpg" },
    "data": "<base64 du JSON storage#object>",
    "messageId": "...",
    "publishTime": "2026-05-24T03:12:45.123Z"
  },
  "subscription": "projects/price-tracker-prod-01/subscriptions/ticket-uploaded-ocr-push"
}
```

Le JSON décodé de `data` est un `storage#object` standard. Champs utiles :
`bucket`, `name`, `contentType`, `size`, `md5Hash`, `generation`, `timeCreated`.

### Réponses HTTP & sémantique Pub/Sub


| Code  | Effet Pub/Sub                                       | Quand l'émettre                                                                |
| ----- | --------------------------------------------------- | ------------------------------------------------------------------------------ |
| `204` | ACK (message consommé)                              | Traitement OK **ou** échec définitif non-retryable (statut `ocr_failed` écrit) |
| `5xx` | NACK → retry (backoff 10s–600s, 5 essais max → DLQ) | Erreur transitoire : Cloud SQL down, Vertex 5xx, GCS 5xx                       |
| `400` | ACK (Pub/Sub considère le message bad)              | Payload Pub/Sub malformé (jamais retryable)                                    |


**Règle d'or** : *ne jamais 500 sur un ticket "empoisonné"* (image corrompue, MIME non supporté, user_id introuvable). Marquer `tickets.status='ocr_failed'`, logger, répondre `204`. Le DLQ doit rester réservé aux pannes infra.

`ack_deadline_seconds = 600` (cf. subscriptions.tf) → **budget temps total par message : 10 min**.

---

## 3. Authentification

OIDC bearer obligatoire sur `/push`. Vérification identique à worker-ingestion / worker-off (cf. [workers/off/pricetracker_off/auth.py](../workers/off/pricetracker_off/auth.py)).

- **Issuer attendu** : `https://accounts.google.com` (`accounts.google.com` accepté aussi).
- **Audience attendu** : URL du service Cloud Run (résolue dynamiquement via `x-forwarded-host`, ou via env `PRT_OIDC_REQUIRED_AUDIENCE`).
- **Allowlist email** : `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS` = `prt-prod-worker-sa@price-tracker-prod-01.iam.gserviceaccount.com`.
- **Bypass local** : `PRT_OIDC_DISABLE=1` (jamais en prod).

Réutiliser `verify_oidc` du worker OFF tel quel.

---

## 4. Variables d'environnement (convention `PRT_*`)

À déclarer dans `infra/envs/prod/cloud_run.tf` module `run_worker_ocr` (à compléter).


| Variable                                                 | Exemple / Valeur                                             | Source                                      |
| -------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------- |
| `GOOGLE_CLOUD_PROJECT`                                   | `price-tracker-prod-01`                                      | env                                         |
| `PRT_GCP_REGION`                                         | `europe-west1`                                               | env                                         |
| `PRT_BRONZE_BUCKET`                                      | `price-tracker-prod-01-bronze`                               | env                                         |
| `PRT_MODELS_BUCKET`                                      | `price-tracker-prod-01-models`                               | env                                         |
| `PRT_OCR_MODEL_URI`                                      | `gs://price-tracker-prod-01-models/ocr/v1.0/`                | env                                         |
| `PRT_OCR_ENGINE`                                         | `paddleocr` | `tesseract`                                    | env                                         |
| `PRT_OCR_CONFIDENCE_THRESHOLD`                           | `0.55`                                                       | env                                         |
| `PRT_EAN_MATCH_COSINE_THRESHOLD`                         | `0.78`                                                       | env                                         |
| `PRT_EAN_MATCH_TOP_K`                                    | `5`                                                          | env                                         |
| `PRT_EAN_FUZZY_MIN_SCORE`                                | `82`                                                         | env                                         |
| `PRT_VERTEX_MODEL`                                       | `text-embedding-004` (**identique au worker OFF**)           | env                                         |
| `PRT_VERTEX_OUTPUT_DIM`                                  | `768`                                                        | env                                         |
| `PRT_VERTEX_TASK_TYPE`                                   | `RETRIEVAL_QUERY` (≠ OFF qui utilise `RETRIEVAL_DOCUMENT`)   | env                                         |
| `PRT_PG_HOST` / `_PORT` / `_DB` / `_USER` / `_POOL_SIZE` | private IP Cloud SQL, `5432`, `price_tracker`, `pt_app`, `4` | env                                         |
| `PRT_PG_PASSWORD`                                        | (secret)                                                     | Secret Manager `prt-prod-cloudsql-password` |
| `PRT_OIDC_ALLOWED_SERVICE_ACCOUNTS`                      | worker-sa email                                              | env                                         |
| `PRT_LOG_LEVEL`                                          | `INFO`                                                       | env                                         |


> ⚠️ `PRT_VERTEX_TASK_TYPE=RETRIEVAL_QUERY` côté OCR (texte de ligne de ticket = "requête") face à `RETRIEVAL_DOCUMENT` côté OFF (fiche produit = "document"). C'est ce que Vertex attend pour aligner les espaces vectoriels — ne pas inverser.

---

## 5. Accès data — qui lit/écrit quoi


| Ressource                        | Mode | Comment                                             |
| -------------------------------- | ---- | --------------------------------------------------- |
| `gs://…-bronze/tickets/raw/`**   | R    | Direct VPC egress + worker-sa `objectAdmin`         |
| `gs://…-models/ocr/<version>/**` | R    | worker-sa `objectViewer` (déjà OK)                  |
| Cloud SQL `tickets`              | R/W  | UPDATE only (la row existe déjà, créée par backend) |
| Cloud SQL `prix_extraits`        | W    | INSERT batch                                        |
| Cloud SQL `product_aliases`      | W    | INSERT candidat (`validated_by_user=false`)         |
| Cloud SQL `products`             | R    | SELECT pgvector pour matching EAN                   |
| Vertex AI text-embedding-004     | R    | embed des libellés bruts OCR                        |
| BigQuery                         | —    | **AUCUN accès** (OCR ne touche pas BQ)              |


L'IAM est déjà posée pour `prt-prod-worker-sa` (cf. Phase 2 & 4).

---

## 6. Schéma SQL attendu (à proposer au backend pour Alembic Phase 7)

Le worker OCR conditionne ces schémas. Le développeur backend les implémentera ; **rester aligné** avec ces noms de colonnes pour éviter une refonte plus tard.

```sql
-- 6.1 tickets (créée par backend au moment du Signed URL)
CREATE TYPE ticket_status AS ENUM (
  'pending',         -- backend a signé l'URL, image pas encore uploadée
  'uploaded',        -- GCS finalize reçu (transitoire, set par OCR au début)
  'ocr_processing',  -- OCR en cours
  'ocr_done',        -- OCR OK, en attente de validation user
  'ocr_failed',      -- OCR a échoué définitivement
  'validated'        -- user a confirmé les articles
);

CREATE TABLE tickets (
  id              uuid PRIMARY KEY,                 -- == {uuid} du nom de fichier GCS
  user_id         uuid NOT NULL REFERENCES users(id),
  gcs_object_path text NOT NULL UNIQUE,             -- "tickets/raw/{user_id}/{uuid}.jpg"
  status          ticket_status NOT NULL DEFAULT 'pending',
  enseigne        text,                             -- détectée OCR (header)
  ticket_date     date,                             -- date d'achat parsée
  total_amount    numeric(10,2),                    -- total lu sur le ticket
  ocr_confidence  real,                             -- score global [0,1]
  ocr_engine      text,                             -- "paddleocr" / "tesseract" / version
  ocr_duration_ms integer,
  error_message   text,                             -- non-null si status='ocr_failed'
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- 6.2 prix_extraits (insertion OCR)
CREATE TABLE prix_extraits (
  ticket_id        uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  line_index       smallint NOT NULL,               -- 0..N, ordre de lecture du ticket
  raw_text         text NOT NULL,                   -- libellé OCR brut
  quantity         numeric(8,3),                    -- 1.000 par défaut si non parsé
  unit_price       numeric(10,2),
  line_total       numeric(10,2),
  ean              text,                            -- NULL si non résolu
  match_method     text,                            -- "vector" | "fuzzy" | "none"
  match_confidence real,                            -- [0,1]
  needs_validation boolean NOT NULL DEFAULT true,
  validated_by_user boolean NOT NULL DEFAULT false,
  PRIMARY KEY (ticket_id, line_index)               -- ← idempotence
);

-- 6.3 product_aliases (candidats OCR)
CREATE TABLE product_aliases (
  raw_text          text NOT NULL,
  ean               text NOT NULL,
  enseigne          text,
  confidence        real NOT NULL,
  validated_by_user boolean NOT NULL DEFAULT false,
  occurrences       integer NOT NULL DEFAULT 1,
  first_seen_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (raw_text, ean)
);
```

**Idempotence** : `INSERT … ON CONFLICT (ticket_id, line_index) DO UPDATE`. Un retry Pub/Sub ne doit jamais dupliquer de lignes.

---

## 7. Pipeline interne (suggéré, non normatif)

```
POST /push
  ├─ verify_oidc                                       (401 si KO)
  ├─ parse Pub/Sub envelope → gcs_object_path          (400 si KO)
  ├─ derive ticket_id (= uuid du nom de fichier)
  ├─ UPDATE tickets SET status='ocr_processing' WHERE id=$1 AND status IN ('pending','uploaded')
  │   └─ si 0 rows → ACK (idempotent : déjà traité ou réessai tardif)
  ├─ download GCS → bytes (limite 10 MB ; si > → status='ocr_failed', ACK)
  ├─ preprocess (deskew, denoise, binarize)
  ├─ OCR inference → [(text, bbox, conf), ...]
  ├─ parse → { enseigne, date, lines: [...], total }
  ├─ pour chaque ligne :
  │     ├─ embed(raw_text) via Vertex (RETRIEVAL_QUERY)
  │     ├─ SELECT ean FROM products ORDER BY embedding <=> $1 LIMIT 5
  │     ├─ si top1_cosine ≥ 0.78 → match_method='vector'
  │     ├─ sinon → fuzzy sur product_aliases.raw_text (rapidfuzz, seuil 82)
  │     └─ sinon → ean=NULL, needs_validation=true
  ├─ UPDATE tickets SET status='ocr_done', enseigne=…, ticket_date=…, total_amount=…, ocr_confidence=…
  ├─ INSERT prix_extraits (batch, ON CONFLICT UPDATE)
  ├─ UPSERT product_aliases (occurrences+1, last_seen_at=now())
  └─ 204
```

---

## 8. EAN nouveaux découverts par OCR — handoff vers OFF

Quand l'OCR résout un EAN qui **n'existe pas dans `products`** (cas rare car OFF a déjà couvert le catalogue Open Prices, mais possible pour produits régionaux), il l'écrit quand même dans `prix_extraits.ean`. **Il n'enrichit pas.**

Côté worker OFF, la query de discovery devra être étendue (Phase 6.3, hors scope OCR) pour inclure :

```sql
SELECT DISTINCT ean FROM prix_extraits
WHERE ean IS NOT NULL
  AND ean NOT IN (SELECT ean FROM products)
```

→ flagger ce besoin dans la PR OCR, à traiter par le dev OFF / Indices.

---

## 9. Modèle OCR — stockage & chargement

- **Bucket** : `gs://price-tracker-prod-01-models/ocr/<version>/` (versionning ON).
- **Chargement** : au cold start, télécharger en `/tmp` (writable sur Cloud Run, ~5 GB dispo). Cache en mémoire pour les invocations chaudes.
- **Versioning** : `PRT_OCR_MODEL_URI` est la seule source de vérité. Bump = nouveau prefix GCS, jamais d'écrasement.
- **Sortie modèle** ≠ sortie worker : le retour brut du modèle (texte + bbox + conf) reste interne ; ce qui sort vers SQL est le résultat *parsé et enrichi* (cf. §6.2). Ne pas leak la structure interne du modèle dans `prix_extraits`.

---

## 10. Runtime Cloud Run

À ajuster dans [infra/envs/prod/cloud_run.tf](../infra/envs/prod/cloud_run.tf) `module "run_worker_ocr"` :


| Param                   | Valeur cible Phase 8                                    |
| ----------------------- | ------------------------------------------------------- |
| `memory`                | `2Gi` (PaddleOCR ~1.2Gi) — bench obligatoire avant bump |
| `cpu`                   | `2` (CPU-bound sur OCR inference)                       |
| `min_instances`         | `0`                                                     |
| `max_instances`         | `5` (cf. cloud_run.tf actuel)                           |
| `timeout_seconds`       | `540` (< ack_deadline 600s, marge pour ACK)             |
| `ingress`               | `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` (déjà OK)      |
| `vpc_egress`            | `PRIVATE_RANGES_ONLY` (déjà OK pour Cloud SQL)          |
| `service_account_email` | `prt-prod-worker-sa`                                    |


---

## 11. Layout repo & build

Calque sur `workers/off/` (proven Phase 6.5) :

```
workers/ocr/
├── Dockerfile                       # python:3.11-slim multi-stage, COPY model n'est PAS embedded (téléchargé runtime)
├── cloudbuild.yaml                  # build → push artifact-registry/prt-prod-docker/worker-ocr:<sha>
├── pyproject.toml                   # fastapi, uvicorn, google-cloud-storage, google-cloud-aiplatform,
│                                    # asyncpg, paddleocr (ou pytesseract), pillow, opencv-python-headless,
│                                    # rapidfuzz, structlog, pydantic-settings
├── .dockerignore / .gcloudignore
├── pricetracker_ocr/
│   ├── __init__.py
│   ├── main.py                      # FastAPI + /push + /healthz
│   ├── auth.py                      # COPIER de workers/off — ne pas réimplémenter
│   ├── config.py                    # Settings pydantic-settings (PRT_*)
│   ├── logging.py                   # COPIER de workers/off
│   ├── gcs.py                       # download image
│   ├── preprocess.py                # opencv pipeline
│   ├── ocr_engine.py                # wrapper PaddleOCR/Tesseract (Strategy)
│   ├── parser/                      # heuristiques par enseigne (leclerc.py, lidl.py, carrefour.py, default.py)
│   ├── matcher.py                   # vector + fuzzy
│   ├── vertex.py                    # COPIER de workers/off, juste changer task_type
│   ├── pg.py                        # asyncpg pool + UPSERT prix_extraits + aliases
│   └── pubsub.py                    # parsing envelope + dedup messageId (cache LRU optionnel)
└── tests/                           # pytest : fixtures images, mock Vertex/pg/GCS
```

**Image tag bump** : ajouter `worker_ocr_image_tag` à `variables.tf`, propager dans `cloud_run.tf` à l'identique de `worker_off_image_tag`.

---

## 12. Logging & observabilité

`structlog` JSON sur stderr (capté par Cloud Logging). Champs minimaux par event :

```python
log.info("ocr_done",
    ticket_id=..., user_id=..., gcs_path=...,
    duration_ms=..., n_lines=..., n_resolved_vector=..., n_resolved_fuzzy=...,
    n_needs_validation=..., ocr_confidence=...,
    image_bytes=..., model_version=...)
```

Events nommés attendus : `push_received`, `ocr_start`, `ocr_done`, `ocr_failed`, `ean_match_vector`, `ean_match_fuzzy`, `ean_unresolved`, `pg_upsert_done`.

---

## 13. Tests minimum requis

- **Unit** : parser par enseigne (fixtures texte OCR brut → structure parsée).
- **Unit** : matcher (mock pgvector + fuzzy).
- **Integration** : pipeline complet avec `testcontainers-postgres` + image `pgvector/pgvector:pg15` + mock Vertex + image fixture.
- **Contract** : POST /push avec une enveloppe Pub/Sub réelle (sample dans `tests/fixtures/`).
- **Idempotence** : rejouer 2× le même message → `prix_extraits` identique, pas de duplication.

---

## 14. Checklist intégration (à valider avant merge)

- `POST /push` retourne `204` sur happy path et sur image corrompue (jamais 500 pour cause data)
- OIDC vérifié (allowlist = worker-sa)
- Idempotent sur `(ticket_id, line_index)` et sur replay Pub/Sub
- P95 de bout en bout < 480s (sous l'ack_deadline 600s avec marge)
- Embedding model = `text-embedding-004` dim 768, task_type=`RETRIEVAL_QUERY`
- Aucun accès BigQuery
- Aucune création SA, secret, IAM hardcodée — tout via Terraform
- Pas de clé JSON SA (org policy `iam.disableServiceAccountKeyCreation`) — ADC uniquement
- Logs JSON structurés avec `ticket_id` dans chaque event
- Dockerfile + cloudbuild.yaml calqués sur `workers/off/`
- Tag image piloté par `var.worker_ocr_image_tag` (Terraform)

