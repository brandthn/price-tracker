# Open Prices Pipeline

Pipeline data engineering GCP pour ingestion, nettoyage, enrichissement et agrégation de prix alimentaires issus du dataset Open Food Facts / Open Prices.

## Stack

- Python 3.11
- Google Cloud Run
- Google Cloud Storage
- BigQuery
- Cloud Scheduler
- Terraform
- Docker

## Architecture

Le pipeline suit une architecture **Bronze / Silver / Gold** :

- **Bronze** : snapshot brut Hugging Face stocké dans GCS
- **Silver** : données nettoyées et validées dans BigQuery
- **Gold** : agrégats hebdomadaires et signaux analytiques dans BigQuery

## Workers

- `worker_ingestion` : télécharge le snapshot, nettoie et charge Silver
- `worker_off` : enrichit les EAN manquants via Open Food Facts
- `worker_indices` : calcule agrégats, anomalies et indices
- `worker_alertes` : prépare les alertes à partir des anomalies

## Pré-requis

- Python 3.11+
- Docker
- gcloud CLI
- Terraform >= 1.6
- Un projet GCP actif avec facturation activée
- APIs GCP activées :
  - Cloud Run Admin API
  - Cloud Build API
  - Artifact Registry API
  - Cloud Scheduler API
  - BigQuery API
  - Cloud Storage API

## Variables principales

Copier `.env.example` vers `.env` :

```bash
cp .env.example .env
```

## Installation locale

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r worker_ingestion/requirements.txt
pip install -r worker_off/requirements.txt
pip install -r worker_indices/requirements.txt
pip install -r worker_alertes/requirements.txt
pip install pytest
```

## Lancer les tests

```bash
bash scripts/run_tests.sh
```

## Déploiement infra

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

## Déploiement applicatif

```bash
bash scripts/deploy.sh
```

## Exécution locale d’un worker

Exemple :

```bash
export WORKER_NAME=worker_ingestion
python worker_ingestion/main.py
```

## Buckets GCS

- Bronze : snapshots bruts
- Signals : états d’exécution entre workers
- Artifacts : artefacts techniques éventuels

## Tables BigQuery

### Silver

- `openpricesclean`
- `openpricesrejections`
- `catalogueproduits`

### Gold

- `aggregatsenseignes`
- `indicesinflation`
- `rankingsproduits`
- `anomaliesdetected`

## Principes de qualité

- validation stricte à l’ingestion
- quality gates bloquants
- partitionnement BigQuery
- logs structurés
- coût cloud réduit

## Roadmap V2

- Cloud SQL pour profils utilisateur et préférences
- alertes email / push réelles
- enrichissement régional INSEE
- orchestration avancée
- monitoring cloud avancé