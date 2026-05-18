# `infra/` — Terraform GCP

Infrastructure as Code de PriceTracker. Phases 1 (state + SAs), 2 (storage, network, AR, secrets), 4 (Cloud SQL + BigQuery + Pub/Sub + GCS notifications) et 5 (Cloud Run skeleton + Cloud Scheduler + push subscription Pub/Sub) complétées. Phase 3 (CI/CD WIF) **non encore implémentée** — un seul opérateur lance `terraform apply` en attendant.

## Structure Repo

```
infra/
├── envs/
│   └── prod/                 # Composition Terraform — UNIQUE racine à init/plan/apply
│       ├── versions.tf
│       ├── backend.tf        # gcs prefix=envs/prod
│       ├── variables.tf
│       ├── locals.tf         # SA members convenience + lifecycle defaults
│       ├── main.tf           # provider + tf-state bucket + module iam (4 SAs)
│       ├── network.tf        # module network (VPC + subnet + PSA)
│       ├── storage.tf        # 3 buckets : bronze, silver, models
│       ├── artifact_registry.tf
│       ├── secret_manager.tf
│       ├── cloud_sql.tf      # Phase 4 — Postgres 15 private IP
│       ├── bigquery.tf       # Phase 4 — datasets silver/gold/ml
│       ├── pubsub.tf         # Phase 4 — topic ticket-uploaded + Phase 5 — DLQ topic
│       ├── notifications.tf  # Phase 4 — GCS bronze → Pub/Sub
│       ├── cloud_run.tf      # Phase 5 — 6 services Cloud Run (skeleton hello) + run.invoker IAM
│       ├── cloud_scheduler.tf # Phase 5 — 4 cron jobs HTTP+OIDC
│       ├── service_agents.tf # Phase 5 — service agents Scheduler/Pub/Sub (lazy) + tokenCreator
│       ├── subscriptions.tf  # Phase 5 — push sub ticket-uploaded→worker-ocr + DLQ inspection
│       ├── outputs.tf
│       └── terraform.tfvars.example
├── modules/
│   ├── iam/                  # SAs + project IAM bindings
│   ├── network/              # VPC + subnet + Private Services Access
│   ├── storage/              # Bucket générique paramétré (lifecycle, IAM)
│   ├── artifact_registry/    # Docker repo + IAM bindings
│   ├── secret_manager/       # Secrets + secretAccessor bindings
│   ├── cloud_sql/            # Postgres + random password + push to secret
│   ├── bigquery/             # Datasets + dataset-level IAM
│   ├── pubsub/               # Topics + topic-level IAM
│   ├── cloud_run/            # Service Cloud Run v2 + Direct VPC egress + secrets
│   └── cloud_scheduler/      # Jobs HTTP avec OIDC token
└── sql/
    └── bootstrap_pgvector.sql  # One-shot post-apply : CREATE EXTENSION vector
```

Un seul `terraform init` à faire, depuis `infra/envs/prod/`. Tous les modules `infra/modules/` sont réutilisables tels quels (paramétrés, pas de hardcoding).

> `envs/prod/` est conservé même avec un seul env pour laisser la porte ouverte à un futur `envs/dev/` sans restructurer.

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

## Service Accounts

| SA | Usage | Rôles projet | Rôles resource-level |
|---|---|---|---|
| `prt-prod-terraform-sa` | Exécutions `terraform apply` (impersonation) | `editor`, `resourcemanager.projectIamAdmin`, `iam.serviceAccountAdmin`, `iam.serviceAccountUser`, `storage.admin`, `serviceusage.serviceUsageAdmin` | — |
| `prt-prod-backend-sa` | Cloud Run backend FastAPI (Phase 7) | `logging.logWriter`, `monitoring.metricWriter`, `cloudtrace.agent`, `cloudsql.client`, `cloudsql.instanceUser`, `bigquery.jobUser` | bronze=`objectAdmin`, silver=`objectViewer`, AR=`reader`, secret cloudsql=`accessor`, BQ datasets silver/gold/ml=`dataViewer` |
| `prt-prod-worker-sa` | Workers Cloud Run (OCR + ingestion + OFF + indices + alertes) | `logging.logWriter`, `monitoring.metricWriter`, `cloudtrace.agent`, `cloudsql.client`, `cloudsql.instanceUser`, `bigquery.jobUser`, `aiplatform.user` | bronze=`objectViewer`, silver=`objectAdmin`, models=`objectViewer`, AR=`reader`, secrets cloudsql+hf=`accessor`, BQ datasets silver/gold/ml=`dataEditor`, topic ticket-uploaded=`subscriber` |
| `prt-prod-gh-actions-sa` | Impersonné par GitHub Actions via WIF (Phase 3) | _aucun_ | AR=`writer` |

Les rôles applicatifs additionnels (Cloud SQL Client, BQ Job/Data User, Pub/Sub Subscriber, Vertex AI User, FCM Sender…) seront ajoutés par les modules des phases suivantes, sur les ressources concernées.

> ⚠️ `roles/editor` sur `terraform-sa` reste large. Acceptable pour un projet école avec Free Trial. À durcir si on passe en multi-env.

## Ressources Phase 2

### Buckets GCS (data lake)

| Nom | Versioning | Lifecycle | Usage |
|---|---|---|---|
| `price-tracker-prod-01-bronze` | ON | STANDARD→NEARLINE @ 30j, delete @ 90j | Tickets bruts uploadés |
| `price-tracker-prod-01-silver` | OFF | STANDARD→NEARLINE @ 30j, delete @ 90j | Parquet nettoyés (OpenPrices, OFF) |
| `price-tracker-prod-01-models` | ON | Versions non-courantes deleted @ 90j | Poids modèles OCR + embeddings |
| `price-tracker-prod-01-tf-state` | ON | versioning rotation à 30 versions, delete @ 90j | State Terraform (importé) |

> Le bucket `bronze` garde le versioning ON pour pouvoir récupérer un ticket corrompu pendant la fenêtre de rétention. `silver` n'en a pas besoin (toujours reproductible depuis bronze).

### Réseau

| Ressource | Nom | CIDR | Notes |
|---|---|---|---|
| VPC | `prt-vpc` | — | custom mode (auto subnets = false) |
| Subnet primaire | `prt-subnet-ew1` | `10.10.0.0/24` | europe-west1, `private_ip_google_access=true`. Cloud Run y attache via Direct VPC egress (Phase 5). |
| Private Services Access | `prt-psa-range` | `10.20.0.0/16` | Peering avec services Google (Cloud SQL Phase 4) |

> **Pas de Serverless VPC Connector** : remplacé par Direct VPC egress (GA 2024, 0 $/mois). Cloud Run en Phase 5 se branchera directement sur `prt-subnet-ew1` via le bloc `network_interfaces` du service.

### Artifact Registry

`prt-prod-docker` en `europe-west1`, format Docker. Politique de nettoyage : garder les 10 dernières versions par image.

URL : `europe-west1-docker.pkg.dev/price-tracker-prod-01/prt-prod-docker/<image>:<tag>`

### Secrets

| Secret | Populé par | Accessors |
|---|---|---|
| `prt-prod-cloudsql-password` | **AUTO** Phase 4 (Terraform `random_password` + version pushée à Secret Manager) | backend-sa, worker-sa |
| `prt-prod-hf-token` | **MANUEL** post-apply Phase 2 (cf. runbook §B ci-dessous) | worker-sa |

> Les secrets sont créés vides par Terraform (containers + IAM seulement). Sans valeur ajoutée, toute lecture par le backend/worker échouera (`NotFound`). Les sections suivantes détaillent comment ajouter la valeur réelle.

> **Pas de secret Firebase Admin SDK** : l'org `b-niyungeko-org` enforce la policy `iam.disableServiceAccountKeyCreation` (default GCP depuis 2024). La création de clé JSON pour le service account `firebase-adminsdk-fbsvc@…` échoue donc en console. C'est aligné avec les best practices 2026 : le backend utilisera **ADC** (Application Default Credentials) — voir §A pour l'activation Firebase, et la note Phase 7 dans `.claude/plans/plan-01.md` pour le code backend.

## Runbook — Populer les secrets post-apply Phase 2

### A. Firebase Auth — activation projet (pas de secret à pousser)

**Ce qu'on configure** : Firebase Auth (Email/Password) pour gérer l'authentification utilisateur côté frontend (Phase 10). Le backend FastAPI (Phase 7) **vérifiera** les JWT émis par Firebase via la lib `firebase-admin`.

**Pourquoi pas de clé JSON ?** L'org `b-niyungeko-org` enforce `iam.disableServiceAccountKeyCreation` (default GCP depuis 2024) → la console Firebase refuse de générer une clé pour le SA `firebase-adminsdk-fbsvc@…`. C'est en réalité une bonne nouvelle : Google recommande depuis 2024 d'utiliser **ADC** (Application Default Credentials) plutôt que des clés long-lived. Le backend FastAPI sur Cloud Run utilisera automatiquement la SA attachée (`prt-prod-backend-sa`).

> Pour la simple vérification de JWT (use case backend), **aucun rôle IAM n'est requis** : `firebase_admin.auth.verify_id_token()` télécharge les certs publics de Google (`securetoken@system.gserviceaccount.com`) et fait la vérif côté client. Si plus tard on a besoin d'**opérations admin** Firebase (créer/supprimer des users, custom claims), il faudra ajouter `roles/firebaseauth.admin` à `prt-prod-backend-sa` — mais toujours **pas de clé JSON**.

#### A.1 — Activer Firebase sur le projet GCP

1. Aller sur https://console.firebase.google.com/
2. Cliquer **« Add project »** → choisir **« Add Firebase to Google Cloud project »**
3. Sélectionner `price-tracker-prod-01` dans la liste déroulante
4. Accepter les conditions, garder « Google Analytics » désactivé (pas utile ici, économise des appels API)
5. Cliquer **« Add Firebase »**, attendre ~30 s

> Vérification : `https://console.firebase.google.com/project/price-tracker-prod-01/overview` doit s'ouvrir sans erreur.

#### A.2 — Activer Firebase Authentication (Email/Password)

1. https://console.firebase.google.com/project/price-tracker-prod-01/authentication
2. Cliquer **« Get started »**
3. Onglet **« Sign-in method »** → activer **« Email/Password »** uniquement (ne pas activer Google/Facebook/etc. pour l'instant)
4. **Save**

#### A.3 — Pour info : code backend Phase 7 (ADC)

```python
# Cloud Run : utilise automatiquement la SA attachée (prt-prod-backend-sa).
# En local : nécessite `gcloud auth application-default login` au préalable.
import firebase_admin
from firebase_admin import auth

firebase_admin.initialize_app()  # ADC, zéro fichier de credentials à charger

# Dans une dependency FastAPI :
decoded = auth.verify_id_token(bearer_token)
user_id = decoded["uid"]
```

Aucun appel à `Secret Manager` côté Firebase. Aucune env var `FIREBASE_*` côté serveur (seul le frontend Next.js a besoin de la config publique `NEXT_PUBLIC_FIREBASE_*`).

---

### B. `prt-prod-hf-token` — HuggingFace API token (READ)

**Ce que c'est** : un token personnel HuggingFace qui permet de télécharger des datasets/modèles depuis le Hub. On en a besoin pour que le worker ingestion (Phase 6.1) puisse pull le snapshot du dataset **`openfoodfacts/open-prices`** quotidiennement.

**Scope nécessaire** : `READ` uniquement (lecture publique + datasets gated si jamais on en utilise plus tard).

#### B.1 — Créer un compte HuggingFace (si pas déjà)

1. https://huggingface.co/join — créer un compte avec ton email
2. Confirmer l'email

> Si plusieurs membres du groupe contribuent, **un seul token suffit** pour le projet. À toi de décider quel compte « porte » le token (ex: créer un compte `price-tracker-bot` partagé, ou utiliser le compte d'un membre).

#### B.2 — Générer le token

1. https://huggingface.co/settings/tokens
2. Cliquer **« + Create new token »**
3. Onglet **« Read »** (pas Write)
4. Nom : `price-tracker-prod-ingestion` (juste pour t'y retrouver si tu en crées plusieurs)
5. Cliquer **« Create token »**
6. **Copier la valeur affichée** (commence par `hf_…`) — elle ne sera plus affichée après fermeture de la modale

#### B.3 — Pousser dans Secret Manager

```bash
# Lire le token sans le faire apparaître dans l'historique shell (-s) et le piper directement
# Tu seras prompté → coller la valeur hf_xxx puis Entrée
read -s HF_TOKEN

echo -n "$HF_TOKEN" | gcloud secrets versions add prt-prod-hf-token \
  --data-file=- --project=price-tracker-prod-01

# Effacer le token de la variable shell
unset HF_TOKEN

# Vérifier la création de la version
gcloud secrets versions list prt-prod-hf-token --project=price-tracker-prod-01
```

> Le `echo -n` (sans newline final) évite qu'un `\n` parasite ne se retrouve dans la valeur du secret.

---

### Vérification globale

```bash
# Doit lister 2 secrets (cloudsql-password + hf-token) ; pas de firebase-admin (cf. §A)
gcloud secrets list --project=price-tracker-prod-01 --filter="name~prt-prod-"

# hf-token doit avoir une version active après §B
gcloud secrets versions list prt-prod-hf-token --project=price-tracker-prod-01 --limit=1

# cloudsql-password : version générée AUTO par Terraform en Phase 4
gcloud secrets versions list prt-prod-cloudsql-password --project=price-tracker-prod-01 --limit=1
```

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

## Ressources Phase 4

> ⚠️ **Collaboration groupe** : tant que la Phase 3 (CI/CD via GitHub Actions WIF) n'est pas en place, **un seul membre désigné** lance `terraform apply`. Deux `apply` concurrents = state désynchronisé. Prévenir le groupe sur Slack/Discord avant chaque apply.

### Cloud SQL

| Ressource | Valeur |
|---|---|
| Instance | `prt-prod-sql-main` (POSTGRES_15, `db-g1-small`, **ZONAL** = HA off) |
| Disque | 10 GB SSD, auto-resize ON |
| Network | **Private IP only** (pas d'IP publique), VPC `prt-vpc`, peering PSA `prt-psa-range` |
| Database | `price_tracker` |
| User applicatif | `pt_app` (mot de passe random 32 chars → secret `prt-prod-cloudsql-password` v1) |
| IAM database auth | **ON** (`cloudsql.iam_authentication=on`) — les SAs peuvent à terme se connecter via Cloud SQL Auth Proxy sans mot de passe |
| Backups | Quotidiens 03h00 UTC, **PITR ON** (7j de WAL retention) |
| Maintenance | Dimanche 04h00 UTC, track `stable` |
| Deletion protection | **ON** — pour détruire, éditer `cloud_sql.tf` → `deletion_protection=false`, apply, puis destroy |

> Coût mensuel estimé : ~25-28 $/mois (db-g1-small ZONAL + 10 GB SSD + backup quotidien).

### BigQuery

| Dataset | Editors | Viewers | Usage |
|---|---|---|---|
| `prt_prod_silver` | `worker-sa` | `backend-sa` | Open Prices nettoyés (alimenté Phase 6.1), catalogue produits OFF (Phase 6.2). |
| `prt_prod_gold` | `worker-sa` | `backend-sa` | Indices d'inflation, agrégats enseignes, rankings (Phase 9.1). |
| `prt_prod_ml` | `worker-sa` | `backend-sa` | Datasets entraînement / monitoring qualité ML. |

Location multi-région `EU`. IAM appliqué au niveau **dataset** (plus précis qu'au niveau projet).

### Pub/Sub & GCS notifications

| Ressource | Détail |
|---|---|
| Topic Pub/Sub | `ticket-uploaded` (retention 7j, max Pub/Sub standard) |
| GCS notification | `bucket=…-bronze`, `prefix=tickets/raw/`, `event_types=[OBJECT_FINALIZE]`, `payload_format=JSON_API_V1`, `topic=ticket-uploaded` |
| Service agent GCS | `service-{project_number}@gs-project-accounts.iam.gserviceaccount.com` reçoit `pubsub.publisher` sur le topic |
| Subscriber | `worker-sa` (préparation Phase 8 : worker OCR créera sa push subscription) |

> **Changement vs plan initial** : on utilise `google_storage_notification` au lieu d'un trigger Eventarc. Pourquoi ? Filtre `object_name_prefix` natif (Eventarc ne le supporte pas), 1 ressource au lieu de 4, aucun coût d'overhead. Fonctionnellement équivalent côté consommateur.

## Runbook — Bootstrap pgvector (post-apply Phase 4)

L'extension `vector` doit être activée **une fois** après le premier `terraform apply` de Phase 4. Terraform ne le fait pas lui-même car le provider `postgresql` exige une connectivité réseau qu'on n'a pas depuis le runner local (private IP only). Trois options, par ordre de simplicité :

### Option 1 — Cloud SQL Studio (le plus simple, recommandé)

1. Console GCP → SQL → cliquer `prt-prod-sql-main` → onglet **« Studio »**
2. Première connexion : choisir database `price_tracker`, user `pt_app`, password = contenu du secret :
   ```bash
   gcloud secrets versions access latest --secret=prt-prod-cloudsql-password --project=price-tracker-prod-01
   ```
3. Coller le contenu de `infra/sql/bootstrap_pgvector.sql` dans l'éditeur, cliquer **Run**.
4. Vérifier le résultat : doit afficher `vector | <version>` (ex. `0.7.0`).

### Option 2 — Cloud SQL Auth Proxy en local

```bash
# Une seule fois — récupérer le proxy
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.11.0/cloud-sql-proxy.darwin.arm64
chmod +x cloud-sql-proxy

# Démarrer le proxy en background (private-ip = bypass VPC peering)
./cloud-sql-proxy --private-ip price-tracker-prod-01:europe-west1:prt-prod-sql-main &
# → écoute sur localhost:5432

# Récupérer le password
PGPASSWORD=$(gcloud secrets versions access latest \
  --secret=prt-prod-cloudsql-password --project=price-tracker-prod-01)

# Exécuter le bootstrap
PGPASSWORD="$PGPASSWORD" psql -h 127.0.0.1 -U pt_app -d price_tracker \
  -f infra/sql/bootstrap_pgvector.sql

# Nettoyer
unset PGPASSWORD
kill %1   # stoppe le proxy
```

> Le proxy en mode `--private-ip` ne fonctionne **pas** depuis ta machine locale si tu n'es pas dans le VPC. Si ça échoue : passe par Option 1 (Cloud SQL Studio) ou Option 3.

### Option 3 — Activer temporairement l'IP publique (à éviter)

Si Options 1 et 2 ne sont pas accessibles : éditer `cloud_sql.tf` pour mettre temporairement `ipv4_enabled=true` + ajouter ton IP en authorized network, faire le bootstrap, puis re-désactiver. Méthode déconseillée (exposition publique même brève) — utiliser Option 1.

### Vérification finale

```bash
# Via Cloud SQL Studio : la requête SELECT du script doit retourner 1 ligne.
# Via psql :
PGPASSWORD="$(gcloud secrets versions access latest --secret=prt-prod-cloudsql-password --project=price-tracker-prod-01)" \
  psql -h 127.0.0.1 -U pt_app -d price_tracker \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
# Attendu : 1 ligne "vector | 0.7.0" (ou version équivalente)
```

## Ressources Phase 5

> ⚠️ **Collaboration groupe** : même règle qu'en Phase 4 — un seul opérateur lance `terraform apply` tant que la Phase 3 (CI/CD WIF) n'est pas en place. Prévenir Slack/Discord avant chaque apply.

### Cloud Run services (skeleton `hello`)

Tous les services tournent en image `us-docker.pkg.dev/cloudrun/container/hello` au déploiement initial. Ils seront remplacés par les vraies images applicatives à mesure que le code arrive (Phase 6, 7, 8, 9). L'image AR sera `europe-west1-docker.pkg.dev/price-tracker-prod-01/prt-prod-docker/<service>:<sha>`.

| Service | SA runtime | Ingress | min / max | CPU / RAM | Usage cible |
|---|---|---|---|---|---|
| `prt-prod-backend` | `prt-prod-backend-sa` | `INGRESS_TRAFFIC_ALL` + `allUsers` invoker | 0 / 3 | 1 / 512Mi | Backend FastAPI (Phase 7). Sera durci derrière un Load Balancer + Firebase JWT en Phase 7. |
| `prt-prod-worker-ocr` | `prt-prod-worker-sa` | `INTERNAL_LOAD_BALANCER` | 0 / 5 | 1 / 512Mi | Worker OCR déclenché par Pub/Sub push (Phase 8). Mémoire à relever à 2Gi en Phase 8. |
| `prt-prod-worker-ingestion` | `prt-prod-worker-sa` | `INTERNAL_LOAD_BALANCER` | 0 / 1 | 1 / 512Mi | Cron 03h UTC — HuggingFace Open Prices → BQ Silver (Phase 6.1). |
| `prt-prod-worker-off` | `prt-prod-worker-sa` | `INTERNAL_LOAD_BALANCER` | 0 / 1 | 1 / 512Mi | Cron 04h UTC — OpenFoodFacts + embeddings Vertex AI (Phase 6.2). |
| `prt-prod-worker-indices` | `prt-prod-worker-sa` | `INTERNAL_LOAD_BALANCER` | 0 / 1 | 1 / 512Mi | Cron 05h UTC — Laspeyres + anomalies → BQ Gold (Phase 9.1). |
| `prt-prod-worker-alertes` | `prt-prod-worker-sa` | `INTERNAL_LOAD_BALANCER` | 0 / 1 | 1 / 512Mi | Cron 07h UTC — push FCM (Phase 9.2). |

Tous les services sont attachés au subnet `prt-subnet-ew1` via **Direct VPC egress** (`vpc_access.network_interfaces`), egress = `PRIVATE_RANGES_ONLY` (seul le trafic vers RFC1918 — donc Cloud SQL private IP — passe par le VPC ; Vertex/BQ/Internet sortent natif). Exécution `EXECUTION_ENVIRONMENT_GEN2` (requise pour Direct VPC egress).

> **Note `INTERNAL_LOAD_BALANCER`** : nom Google trompeur. Ce mode accepte le trafic du VPC interne **+** des services GCP managés (Cloud Scheduler, Pub/Sub push, Eventarc) routé via le edge GCP. Pas de LB à provisionner pour autant.

### Cloud Scheduler — 4 cron jobs (HTTP + OIDC)

| Job | Schedule (UTC) | Cible | SA OIDC | Audience |
|---|---|---|---|---|
| `prt-prod-trigger-ingestion` | `0 3 * * *` | `prt-prod-worker-ingestion` URL | `prt-prod-worker-sa` | URL service |
| `prt-prod-trigger-off` | `0 4 * * *` | `prt-prod-worker-off` URL | `prt-prod-worker-sa` | URL service |
| `prt-prod-trigger-indices` | `0 5 * * *` | `prt-prod-worker-indices` URL | `prt-prod-worker-sa` | URL service |
| `prt-prod-trigger-alertes` | `0 7 * * *` | `prt-prod-worker-alertes` URL | `prt-prod-worker-sa` | URL service |

> Heure FR équivalente : été (CEST UTC+2) = 05/06/07/09h locale · hiver (CET UTC+1) = 04/05/06/08h locale. UTC conservé en interne (convention SRE).

### Pub/Sub — push subscription + DLQ (Phase 5)

| Ressource | Détail |
|---|---|
| Topic DLQ | `ticket-uploaded-dlq` (retention 7j) |
| Subscription push | `ticket-uploaded-ocr-push` : `ticket-uploaded` → `${run_worker_ocr.uri}/push`, OIDC `worker-sa`, ack_deadline 600s, retry backoff 10→600s, DLQ après 5 échecs |
| Subscription DLQ | `ticket-uploaded-dlq-inspection` : pull, retention 7j (inspection humaine) |

### IAM Phase 5 (résumé)

| Binding | Role | Where | Why |
|---|---|---|---|
| Service agent Cloud Scheduler → `worker-sa` | `roles/iam.serviceAccountTokenCreator` | SA-level | Scheduler mint OIDC token en se faisant passer pour worker-sa |
| Service agent Pub/Sub → `worker-sa` | `roles/iam.serviceAccountTokenCreator` | SA-level | Pub/Sub push idem |
| `worker-sa` → 5 workers Cloud Run | `roles/run.invoker` | Cloud Run resource | OIDC iss=worker-sa autorisé à invoquer |
| Service agent Pub/Sub → DLQ topic | `roles/pubsub.publisher` | Topic-level | Forward des messages empoisonnés vers le DLQ |
| Service agent Pub/Sub → push sub | `roles/pubsub.subscriber` | Subscription-level | Lecture pour forward DLQ |
| `worker-sa` → DLQ topic | `roles/pubsub.subscriber` | Topic-level | Replay / inspection |
| `allUsers` → `prt-prod-backend` | `roles/run.invoker` | Cloud Run resource | Hello accessible publiquement (à durcir Phase 7) |

> Service agents Cloud Scheduler / Pub/Sub sont matérialisés via `google_project_service_identity` (provider google-beta) — **jamais hardcodés**.

## Runbook — Phase 5

### Vérifier l'état des Cloud Run

```bash
gcloud run services list --project=price-tracker-prod-01 --region=europe-west1 \
  --format="table(metadata.name,status.url,spec.template.spec.serviceAccountName)"
# Attendu : 6 lignes prt-prod-{backend,worker-ocr,worker-ingestion,worker-off,worker-indices,worker-alertes}
```

### Vérifier le hello backend (public)

```bash
BACKEND_URL=$(terraform output -raw cloud_run_services | jq -r '.["backend"].uri' 2>/dev/null \
  || gcloud run services describe prt-prod-backend --region=europe-west1 \
       --project=price-tracker-prod-01 --format='value(status.url)')
curl -fsS "$BACKEND_URL" | head -5
# Attendu : page HTML "Congratulations! You successfully deployed your first revision..."
```

### Trigger manuel d'un job Scheduler

Aller console : https://console.cloud.google.com/cloudscheduler?project=price-tracker-prod-01 → cliquer **Force run** sur la ligne du job. Ou en CLI :

```bash
gcloud scheduler jobs run prt-prod-trigger-ingestion --location=europe-west1 \
  --project=price-tracker-prod-01
# Le job appellera worker-ingestion ; tant que le service tourne en image hello,
# il répondra 200 immédiatement.
```

### Inspecter les logs d'un worker

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="prt-prod-worker-ingestion"' \
  --limit=20 --project=price-tracker-prod-01 \
  --format="value(timestamp,severity,textPayload)"
```

### Inspecter le DLQ

```bash
# Compter les messages en attente dans le DLQ
gcloud pubsub subscriptions pull ticket-uploaded-dlq-inspection \
  --auto-ack --limit=10 --project=price-tracker-prod-01
# (Auto-ack uniquement si tu veux drainer. Sinon utiliser --limit + Studio.)
```

### Trouver l'URL d'un service (sans Terraform)

```bash
gcloud run services describe prt-prod-worker-ocr \
  --region=europe-west1 --project=price-tracker-prod-01 \
  --format='value(status.url)'
```

## À venir (phases suivantes)

- **Phase 3** (différée) : `infra/modules/wif/` (Workload Identity Federation pour GitHub Actions) + `.github/workflows/`.
- **Phase 5.5** (proposée) : code worker OCR stub via Gemini Vision pour valider le pipeline E2E avant le vrai modèle PaddleOCR/Tesseract de Phase 8.
- **Phase 6** : workers ingestion + OFF (peuplent `prt_prod_silver`).
