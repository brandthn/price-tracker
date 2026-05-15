# `infra/` — Terraform GCP

Infrastructure as Code de PriceTracker. Phase 1 (state bucket + SAs) complétée.

## Arborescence

```
infra/
├── envs/
│   └── prod/           # Composition Terraform — UNIQUE racine à init/plan/apply
│       ├── versions.tf
│       ├── backend.tf          # gcs prefix=envs/prod
│       ├── variables.tf
│       ├── main.tf             # tf-state bucket (importé) + 4 SAs
│       ├── outputs.tf
│       └── terraform.tfvars.example
└── modules/
    └── iam/            # Module générique : SAs + project IAM bindings
        ├── versions.tf
        ├── variables.tf
        ├── main.tf
        └── outputs.tf
```

Un seul `terraform init` à faire, depuis `infra/envs/prod/`. Pas de bootstrap séparé : le bucket de state est importé directement dans la composition prod (cf. *Première utilisation* ci-dessous).

> `envs/prod/` est conservé même avec un seul env pour laisser la porte ouverte à un futur `envs/dev/` sans restructurer. Les modules dans `infra/modules/` sont déjà réutilisables tels quels.

## Convention de nommage

Voir `.claude/plans/plan-01.md` (section *Convention de nommage*).

**TL;DR**

| Catégorie | Pattern |
|---|---|
| GCS buckets (global) | `price-tracker-prod-01-{role}` |
| Cloud SQL / Run / Scheduler / Artifact Registry / Secrets | `prt-prod-{role}` |
| VPC / réseau (sans stage) | `prt-{role}` |
| Service Accounts | `prt-prod-{role}-sa` |
| BQ datasets (underscores) | `prt_prod_{layer}` |
| Pub/Sub topics | `{event-name}` (nom métier) |
| Labels | `app`, `env`, `managed_by`, `component` |

**Tokens** : `prt` (trigram) · `price-tracker` (slug) · `prod` (stage) · `europe-west1` (région) · `EU` (multi-région BQ/GCS).

## Service Accounts (Phase 1)

| SA | Usage | Rôles projet (Phase 1) |
|---|---|---|
| `prt-prod-terraform-sa` | Exécutions `terraform apply` (impersonation depuis humain ou GH Actions) | `editor`, `resourcemanager.projectIamAdmin`, `iam.serviceAccountAdmin`, `iam.serviceAccountUser`, `storage.admin`, `serviceusage.serviceUsageAdmin` |
| `prt-prod-backend-sa` | Cloud Run backend FastAPI (Phase 7) | `logging.logWriter`, `monitoring.metricWriter`, `cloudtrace.agent` |
| `prt-prod-worker-sa` | Tous les workers Cloud Run (OCR + ingestion + OFF + indices + alertes) | `logging.logWriter`, `monitoring.metricWriter`, `cloudtrace.agent` |
| `prt-prod-gh-actions-sa` | Impersonné par GitHub Actions via WIF (Phase 3) | _aucun en Phase 1_ |

Les rôles applicatifs (Cloud SQL Client, Secret Accessor, BQ Job/Data User, Pub/Sub Subscriber, GCS objectAdmin, Vertex AI User, FCM Sender…) seront ajoutés par les modules des phases suivantes, sur les ressources concernées.

> ⚠️ `roles/editor` sur `terraform-sa` reste large. Acceptable pour un projet école avec Free Trial. À durcir si on passe en multi-env.

## Première utilisation (un seul opérateur, une seule fois)

Prérequis : Phase 0 complétée (cf. [docs/setup-gcp.md](../docs/setup-gcp.md)) — projet GCP créé, APIs activées, bucket `price-tracker-prod-01-tf-state` créé manuellement.

```bash
gcloud auth application-default login
gcloud config set project price-tracker-prod-01

cd infra/envs/prod
terraform init                                                # backend gcs (bucket déjà existant)

# Adopter le bucket de state sous gestion Terraform.
# À faire UNE FOIS, par la première personne du groupe qui lance terraform.
# Les suivants tomberont sur un state qui a déjà la ressource → pas d'import à refaire.
terraform import google_storage_bucket.tf_state price-tracker-prod-01-tf-state

terraform plan                                                # 4 SAs + 12-15 project IAM bindings
terraform apply
```

### Membres suivants du groupe

```bash
gcloud auth application-default login
cd infra/envs/prod
terraform init       # télécharge le state depuis GCS, providers, modules
terraform plan       # doit afficher "No changes" si personne n'a modifié l'infra entre-temps
```

Pas d'import à refaire — le state distant connaît déjà toutes les ressources.

## Workflow de modification (projet de groupe)

1. Branche dédiée + PR.
2. En local sur la branche : `terraform fmt -recursive`, `terraform validate`, `terraform plan` → copier-coller le plan dans la PR.
3. Revue + merge.
4. `terraform apply` depuis `main` (manuel jusqu'à la Phase 3 où GH Actions prendra le relais via WIF).

> Le state GCS gère le verrouillage via Cloud Storage object generation — pas de risque de deux applies concurrents.

## Conventions Terraform

- **Versions** : Terraform `>= 1.7`, provider `google ~> 5.0` (lock pinné dans `.terraform.lock.hcl`, **versionné**).
- **State** : un seul state sous `gs://price-tracker-prod-01-tf-state/envs/prod/`.
- **Variables** : valeurs par défaut dans `variables.tf`, override possible via `terraform.tfvars` (non versionné, voir `.tfvars.example`).
- **Modules** : sous `infra/modules/`, paramétrés et réutilisables. Pas de hardcoding de project-id ni de région à l'intérieur.
- **Labels** : tous les `google_*` qui supportent les labels reçoivent au minimum `app=price-tracker`, `env=prod`, `managed_by=terraform`. Un `component` spécifique est ajouté ressource par ressource.
- **Pas de clé JSON SA** : tout passe par ADC (humain) ou WIF (CI, Phase 3). Les `service-account*.json` sont gitignorés par sécurité.

## À venir (phases suivantes)

- **Phase 2** : `infra/modules/{storage,network,artifact_registry,secret_manager}/`.
- **Phase 3** : `infra/modules/wif/` (Workload Identity Federation pour GitHub Actions).
- **Phase 4** : `infra/modules/{cloud_sql,bigquery,pubsub,eventarc}/`.
- **Phase 5** : `infra/modules/{cloud_run,cloud_scheduler}/`.
