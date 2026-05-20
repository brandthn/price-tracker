# Open Prices Pipeline — Guide d’architecture

## 1. Objectif du projet

Open Prices Pipeline est une plateforme data engineering conçue pour alimenter un comparateur de prix alimentaires grand public.

Le pipeline exploite comme source principale le dataset public **Hugging Face / Open Food Facts open-prices** et construit une architecture analytique en plusieurs couches :

- **Bronze** : conservation immuable des snapshots bruts
- **Silver** : données nettoyées, validées et enrichies
- **Gold** : agrégats analytiques prêts à servir une API ou un site web

Le projet répond à quatre cas d’usage métier :

1. Comparaison de prix par produit et par enseigne
2. Historique hebdomadaire des prix
3. Détection d’anomalies et préparation des alertes
4. Calcul d’indices d’inflation par catégorie et enseigne

---

## 2. Architecture générale

Le pipeline est déployé sur Google Cloud Platform avec les composants suivants :

- **Cloud Run** pour exécuter les workers Python
- **Cloud Scheduler** pour lancer les workers chaque nuit
- **Google Cloud Storage** pour stocker :
  - les snapshots bruts Bronze
  - les signaux d’exécution entre workers
  - les artefacts éventuels
- **BigQuery** pour stocker les tables Silver et Gold
- **Artifact Registry** pour héberger les images Docker

### Région cible

- **GCP region** : `europe-west9`
- **Project ID recommandé** : `pa-open-prices`
- **Dataset BigQuery** : `open_prices_dw`

---

## 3. Principe d’orchestration

Le pipeline est volontairement simple et démontrable :

- chaque worker est autonome
- chaque worker peut être relancé indépendamment
- chaque worker publie un **signal JSON** dans GCS à la fin de son exécution
- le worker suivant vérifie que le signal amont existe et qu’il est en succès

### Ordonnancement prévu

- **03h00** — `worker_ingestion`
- **04h00** — `worker_off`
- **05h00** — `worker_indices`
- **07h00** — `worker_alertes`

### Pourquoi cette approche ?

Cette stratégie permet :

- une orchestration légère sans dépendre d’Airflow
- une très bonne lisibilité pour un projet annuel
- une reprise facile en cas d’échec
- un contrôle explicite des dépendances métiers

---

## 4. Couche Bronze / Silver / Gold

### Bronze

La couche Bronze conserve les snapshots bruts téléchargés depuis Hugging Face.

Exemple de chemin :

```text
gs://pa-open-prices-bronze/open-prices/date=2026-05-12/snapshot.parquet
```

Règles :

- jamais de modification en place
- conservation longue durée
- possibilité de retraitement complet

### Silver

La couche Silver contient les données nettoyées et validées.

Tables principales :

- `openpricesclean`
- `openpricesrejections`
- `catalogueproduits`

### Gold

La couche Gold contient les données analytiques prêtes pour consommation API/site.

Tables principales :

- `indicesinflation`
- `aggregatsenseignes`
- `rankingsproduits`
- `anomaliesdetected`

---

## 5. Rôle des workers

### Worker 1 — Ingestion

Responsabilités :

- télécharger le snapshot brut
- l’archiver en Bronze
- nettoyer et valider les prix
- alimenter :
  - `openpricesclean`
  - `openpricesrejections`
- calculer les métriques de qualité
- publier un signal d’exécution

### Worker 2 — OFF

Responsabilités :

- lire les EAN présents dans Silver
- identifier les EAN absents du catalogue
- enrichir via l’API Open Food Facts
- alimenter `catalogueproduits`
- calculer le taux de résolution EAN
- publier un signal d’exécution

### Worker 3 — Indices

Responsabilités :

- lire les partitions récentes de Silver
- calculer les agrégats hebdomadaires
- détecter les anomalies statistiques
- calculer les indices d’inflation
- calculer les rankings de hausses
- publier un signal d’exécution

### Worker 4 — Alertes

Responsabilités :

- lire `anomaliesdetected`
- préparer la matière pour les alertes utilisateurs
- dans cette V1, écrire un rapport de simulation en logs / JSON
- publier un signal d’exécution

---

## 6. Quality gates

Les quality gates sont bloquants.

### Ingestion

- taux d’acceptation des prix >= 60%
- couverture enseigne identifiable >= 70%

### OFF

- taux de résolution EAN catalogue >= 80%

### Indices

- nombre minimum d’observations pour publier un indice : 3

Si un quality gate est franchi négativement :

- le worker écrit un signal `FAILED`
- le worker retourne une erreur HTTP 500 ou lève une exception
- le worker suivant ne démarre pas logiquement

---

## 7. Stratégie de coûts

Le projet a été pensé pour rester peu coûteux.

### Cloud Run

- `min-instances = 0`
- exécution uniquement sur cron
- faible mémoire par défaut
- timeout borné

### BigQuery

- chargements batch
- tables partitionnées
- clustering adapté aux filtres fréquents
- lecture limitée aux partitions utiles

### GCS

- snapshots bruts en archive métier
- signaux JSON légers
- pas de duplication inutile

### Bonnes pratiques budget

- ne jamais faire de `SELECT *` sur l’historique complet sans filtre
- toujours filtrer sur la partition
- éviter les recalculs complets Gold quand un recalcul incrémental suffit
- surveiller les coûts via les budgets/alertes GCP

---

## 8. Structure du dépôt

La racine du dépôt correspond au pipeline (pas de sous-dossier `open-prices-pipeline/`).

```text
.
├── GUIDE.md
├── README.md
├── .env.example
├── .gitignore
│
├── shared/
│   ├── cleaner.py
│   ├── monitoring.py
│   ├── __init__.py
│   └── tests/
│       ├── test_cleaner.py
│       └── test_monitoring.py
│
├── worker_ingestion/
│   ├── main.py
│   ├── download_open_prices.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── worker_off/
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── worker_indices/
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── worker_alertes/
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── __init__.py
│
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── gcs.tf
│   ├── bigquery_silver.tf
│   ├── bigquery_gold.tf
│   ├── cloud_run.tf
│   └── cloud_scheduler.tf
│
└── scripts/
    ├── run_tests.sh
    └── deploy.sh
```

Un dossier `archive/` peut contenir d’anciens essais (dbt, API, etc.) sans faire partie de la V1 décrite ici.

---

## 9. Philosophie de code

Le code de ce dépôt suit les principes suivants :

- simplicité avant sophistication
- séparation claire entre logique métier et infrastructure
- fonctions testables
- logs structurés et explicites
- dépendances réduites
- coût cloud maîtrisé

---

## 10. Ordre de lecture recommandé

1. `GUIDE.md`
2. `README.md`
3. `shared/cleaner.py`
4. `shared/monitoring.py`
5. `worker_ingestion/main.py`
6. `worker_off/main.py`
7. `worker_indices/main.py`
8. `worker_alertes/main.py`
9. `terraform/`
10. `scripts/`

---

## 11. Limites de la V1

Cette première version est conçue pour être :

- claire
- démontrable
- déployable
- peu coûteuse

Elle n’inclut pas encore :

- Cloud SQL PostgreSQL
- pgvector
- Firebase / FCM
- authentification applicative avancée
- observabilité complète type OpenTelemetry
- orchestration Airflow/Composer

Ces briques pourront être ajoutées dans une V2 si le projet évolue.
