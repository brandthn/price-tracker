# Phase 0 — Setup GCP & DevOps locaux

Runbook à exécuter **une seule fois** par membre du projet pour préparer GCP et la machine locale.
Cette phase est **manuelle** : on bootstrap les fondations dont Terraform aura besoin (projet, facturation, APIs, bucket de state).

---

## Paramètres validés

| Variable | Valeur |
|---|---|
| Organisation GCP | `b-niyungeko-org` |
| Project ID | `price-tracker-prod-01` |
| Project Name | `PriceTracker Prod` |
| Région principale | `europe-west1` |
| Multi-region BQ/GCS | `EU` |
| Bucket state Terraform | `price-tracker-prod-01-tf-state` |
| Compte facturation | Free Trial 300$ (`018EB4-6CD066-B0236F`) |

> **À noter** : les project IDs et noms de bucket GCS sont **globaux et immuables**. Le project ID initialement souhaité `price-tracker-prod-01` était déjà pris : on a basculé sur `price-tracker-prod-01`. En cas de nouvelle collision, ajouter un suffixe et mettre à jour ce fichier.

---

## 0.1 Création du projet GCP

### Via Console (recommandé pour le premier setup)

1. Aller sur https://console.cloud.google.com/
2. Sélectionner l'organisation **b-niyungeko-org** dans le picker en haut à gauche
3. **IAM & Admin → Manage Resources → CREATE PROJECT**
   - Project name : `PriceTracker Prod`
   - Project ID : `price-tracker-prod-01` (cliquer "EDIT" pour le forcer ; les IDs sans tirets style `pricetracker-prod` sont déjà pris à l'échelle globale)
   - Organization : `b-niyungeko-org`
   - Location : `b-niyungeko-org` (org root)
4. Cliquer **CREATE**, attendre ~30 s

### Lier la facturation

1. **Billing → Link a billing account**
2. Sélectionner le compte Free Trial (300$)
3. Confirmer

### Vérification

```bash
gcloud projects describe price-tracker-prod-01
gcloud beta billing projects describe price-tracker-prod-01
```

---

## 0.2 Installation des outils locaux (macOS)

```bash
# gcloud
brew install --cask google-cloud-sdk

# Terraform >= 1.7
brew install terraform
terraform version  # vérifier >= 1.7.0

# Docker (Desktop ou Colima)
brew install --cask docker
# OU plus léger :
brew install colima docker
colima start

# Python 3.12
brew install python@3.12
python3.1 --version

# Node 20 (pour frontend)
brew install node@20
node --version  # v20.x

# uv (gestionnaire Python rapide, on l'utilisera pour backend/workers)
brew install uv
```

### Auth gcloud

```bash
gcloud auth login                       # ouvre le navigateur, login avec le compte Google rattaché à l'org b-niyungeko-org
gcloud auth application-default login   # ADC pour Terraform / SDKs
gcloud config set project price-tracker-prod-01
gcloud config set compute/region europe-west1
# Note : `gcloud config set compute/region` proposera d'activer compute.googleapis.com si ce n'est pas déjà fait — accepter (`y`).
```

### Vérification

```bash
gcloud config list                      # doit afficher project=price-tracker-prod-01
gcloud auth list                        # doit afficher ton compte actif
```

---

## 0.3 Activation des APIs GCP

> ⚠️ `gcloud services enable` limite à **20 APIs par appel** (`SU_MAX_BATCH_SIZE_EXCEEDED`). On scinde donc en deux batches.

```bash
# Batch 1 — fondations + data + serverless (15 APIs)
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  serviceusage.googleapis.com \
  compute.googleapis.com \
  storage.googleapis.com \
  storage-api.googleapis.com \
  sqladmin.googleapis.com \
  bigquery.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  pubsub.googleapis.com \
  eventarc.googleapis.com \
  --project=price-tracker-prod-01

# Batch 2 — orchestration, AI, réseau, observabilité, Firebase (12 APIs)
gcloud services enable \
  cloudscheduler.googleapis.com \
  cloudfunctions.googleapis.com \
  aiplatform.googleapis.com \
  servicenetworking.googleapis.com \
  vpcaccess.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  cloudtrace.googleapis.com \
  firebase.googleapis.com \
  identitytoolkit.googleapis.com \
  fcm.googleapis.com \
  fcmregistrations.googleapis.com \
  --project=price-tracker-prod-01
```

> ⏱️ Chaque batch peut prendre **1-2 minutes**. Certaines APIs en propagent d'autres en cascade.

### Vérification

```bash
gcloud services list --enabled --project=price-tracker-prod-01 | wc -l
# devrait retourner ≥ 27 lignes (en-tête + 27 services au moins)
```

---

## 0.4 Création manuelle du bucket de state Terraform

Ce bucket est créé **hors Terraform** pour éviter le problème de l'œuf et la poule (Terraform a besoin d'un backend pour stocker son state).

```bash
# Création
gcloud storage buckets create gs://price-tracker-prod-01-tf-state \
  --project=price-tracker-prod-01 \
  --location=EU \
  --uniform-bucket-level-access \
  --public-access-prevention

# Activer le versioning (CRITIQUE pour pouvoir restaurer un state corrompu)
gcloud storage buckets update gs://price-tracker-prod-01-tf-state \
  --versioning

# Lifecycle : garder 30 versions max, supprimer les versions > 90 jours
cat > /tmp/tf-state-lifecycle.json <<'EOF'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"numNewerVersions": 30}
    },
    {
      "action": {"type": "Delete"},
      "condition": {
        "daysSinceNoncurrentTime": 90,
        "isLive": false
      }
    }
  ]
}
EOF
gcloud storage buckets update gs://price-tracker-prod-01-tf-state \
  --lifecycle-file=/tmp/tf-state-lifecycle.json
```

### Vérification

```bash
gcloud storage buckets describe gs://price-tracker-prod-01-tf-state \
  --format="value(name,location,versioning_enabled,uniform_bucket_level_access,public_access_prevention)"
# Attendu : price-tracker-prod-01-tf-state  EU  True  True  enforced
#
# ⚠️ Ne pas utiliser les paths JSON-API hérités (`versioning.enabled`,
# `iamConfiguration.uniformBucketLevelAccess.enabled`) : `gcloud storage`
# (qui remplace `gsutil`) expose ces champs en snake_case au niveau racine.
# Si tu vois des colonnes vides, c'est probablement un mauvais format string,
# pas un bucket mal configuré — vérifier avec un `describe` sans `--format`.
```

---

## 0.5 Sécurité — IAM minimal pour les membres du groupe

Pour chaque coéquipier qui doit pouvoir développer/déployer :

```bash
# Remplacer EMAIL par l'adresse Google de la personne
EMAIL="prenom.nom@example.com"

gcloud projects add-iam-policy-binding price-tracker-prod-01 \
  --member="user:${EMAIL}" \
  --role="roles/editor"

# Pour pouvoir gérer Terraform state
gcloud storage buckets add-iam-policy-binding gs://price-tracker-prod-01-tf-state \
  --member="user:${EMAIL}" \
  --role="roles/storage.objectAdmin"
```

> ⚠️ `roles/editor` est **trop large** pour la prod réelle. Acceptable pour un projet école avec un groupe restreint et un Free Trial limité. À durcir en Phase 11 si besoin (séparer dev/data/devops roles).

---

## 0.6 Budget alerts (protection Free Trial)

Pour éviter de cramer le crédit accidentellement :

1. Console → **Billing → Budgets & alerts → CREATE BUDGET**
2. Name : `price-tracker-prod-01-budget`
3. Scope : projet `price-tracker-prod-01`
4. Amount : `300 USD` (montant total Free Trial)
5. Alerts thresholds : **50%, 75%, 90%, 100%**
6. Email recipients : tous les membres du groupe

---

## 0.7 Checklist finale Phase 0

Avant de passer à la Phase 1, valider :

- [ ] `gcloud projects describe price-tracker-prod-01` répond sans erreur
- [ ] `gcloud beta billing projects describe price-tracker-prod-01` montre `billingEnabled: true`
- [ ] `gcloud services list --enabled` contient au moins les 27 APIs ci-dessus
- [ ] `gcloud storage ls gs://price-tracker-prod-01-tf-state` fonctionne
- [ ] `gcloud auth application-default print-access-token` retourne un token (pour Terraform)
- [ ] Tous les membres du groupe ont accès au projet
- [ ] Budget alert configurée à 50/75/90/100 %

Une fois cette checklist validée, on attaque **Phase 1 — Bootstrap Terraform** : création de la structure `infra/` et provisioning des Service Accounts.

---

## Annexe — Commandes utiles

```bash
# Lister les comptes de facturation auxquels tu as accès
# (ne montre PAS le solde Free Trial — uniquement ID/nom/état OPEN)
gcloud beta billing accounts list

# Solde Free Trial restant : il n'y a pas de commande gcloud.
# Console → Billing → Overview → bloc "Free trial credit" :
#   https://console.cloud.google.com/billing/018EB4-6CD066-B0236F

# Budgets configurés sur le compte de facturation
gcloud billing budgets list \
  --billing-account=018EB4-6CD066-B0236F

# Coûts détaillés : pas via gcloud. Deux options :
#   1) Console → Billing → Reports (filtrer par projet price-tracker-prod-01)
#   2) Activer l'export BigQuery du billing puis requêter `gcp_billing_export_v1_*`

# Désactiver une API si problème
gcloud services disable <api>.googleapis.com --project=price-tracker-prod-01

# Supprimer le projet (DERNIER RECOURS, irréversible après 30j)
gcloud projects delete price-tracker-prod-01
```
