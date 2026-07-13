# PriceTracker

Suivi de l'inflation alimentaire à partir de vrais tickets de caisse et de données de prix contributives ([Open Prices](https://huggingface.co/datasets/openfoodfacts/open-prices) / Open Food Facts).

---

## Ce que ça fait

**Observatoire (public)** — ce qui augmente, où et dans quelle enseigne, à l'échelle nationale et régionale. Rankings hebdomadaires, indices d'inflation par chaîne, carte départementale.

**Mon budget (compte requis)** — l'utilisateur photographie ses tickets de caisse, l'application les lit automatiquement et suit l'évolution de son panier au fil du temps. Si un produit est disponible moins cher ailleurs, l'app le signale.

---

## Structure du dépôt

```
price-tracker/
├── backend/          FastAPI — API REST (observatoire, tickets, produits, profil)
├── frontend/         Next.js 16 — interface utilisateur
├── workers/
│   ├── ingestion/    Télécharge Open Prices (HuggingFace) → nettoie → BigQuery Silver
│   ├── off/          Enrichit les EAN via Open Food Facts + embeddings Vertex AI
│   ├── indices/      Calcule les indices d'inflation → BigQuery Gold
│   ├── alertes/      Génère le rapport JSON des hausses du jour
│   └── ocr/          Analyse les photos de tickets (Llama 4 Scout via Groq)
└── infra/            Terraform — toute l'infra GCP décrite en code
```

---

## Pipeline de données

Les données passent par trois couches chaque nuit :

- **Bronze** — snapshot Open Prices archivé brut sur GCS (`prices.parquet` depuis HuggingFace)
- **Silver** — nettoyage et validation (10 règles métier, normalisation enseignes, détection outliers IQR), chargé dans BigQuery via MERGE idempotent
- **Gold** — indices d'inflation (Laspeyres 12 semaines), rankings hausses (LAG), anomalies de prix (z-score), agrégats par enseigne

Les workers s'enchaînent chaque nuit dans l'ordre : **03h → 04h → 05h → 07h UTC**.

---

## Lecture des tickets (OCR)

Quand un utilisateur uploade un ticket, l'image part directement dans GCS via une URL signée. Un événement Pub/Sub déclenche le worker OCR qui appelle **Llama 4 Scout** (via Groq) en mode JSON. Le modèle retourne les produits structurés avec leurs prix — pas de regex ni de post-traitement par enseigne.

Trois backends disponibles : `groq` (production), `paddleocr`, `tesseract`.

---

## Infrastructure

Tout est Terraform — un `terraform apply` depuis `infra/envs/prod/` recrée l'ensemble (Cloud Run, BigQuery, Cloud SQL, GCS, Pub/Sub, Cloud Scheduler, Secret Manager, IAM). Les services s'éteignent quand ils ne servent pas (scale-to-zero).

Région : `europe-west1`. Projet GCP : `price-tracker-prod-01`.

---

## Lancer en local

**Backend**
```bash
cd backend
uv sync
# démarrer le proxy Cloud SQL (voir backend/README.md pour les détails)
export PRT_AUTH_DISABLE=1
uv run uvicorn pricetracker_api.main:app --reload --port 8080
```

**Frontend**
```bash
cd frontend
npm install
cp .env.example .env.local   # remplir les variables Firebase
npm run dev
```

**Worker ingestion**
```bash
cd workers/ingestion
uv sync
uv run python -m pricetracker_ingestion.main
```

---

## Déployer

Chaque worker a son propre `cloudbuild.yaml`. Pour rebuilder et déployer :

```bash
gcloud builds submit --config workers/ingestion/cloudbuild.yaml
# puis bumper l'image tag dans infra/envs/prod/cloud_run.tf → terraform apply
```
