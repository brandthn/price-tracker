# PriceTracker — Data Engineering

Projet académique ESGI 5 IABD 2 — Pipeline d'analyse de l'inflation alimentaire.

## Lancement rapide

```bash
# 1. Cloner le projet
git clone https://github.com/votre-equipe/pricetracker
cd pricetracker

# 2. Copier et remplir les variables d'environnement
cp .env.example .env
# → Editer .env avec vos valeurs

# 3. Lancer tous les services
docker compose up -d

# 4. Accéder aux interfaces
# Airflow  : http://localhost:8080  (admin / admin)
# Metabase : http://localhost:3000
# API      : http://localhost:8000/docs
```

## Architecture

| Couche | Outil | Rôle |
|--------|-------|------|
| Ingestion | Python + datasets | Téléchargement HuggingFace & INSEE |
| Stockage brut | DuckDB + Parquet | Fichiers locaux non transformés |
| Transformation | dbt | Nettoyage, modèle en étoile |
| Orchestration | Airflow | Planification quotidienne |
| Serving | PostgreSQL + FastAPI | API publique |
| Dashboard | Metabase | Visualisation gratuite |