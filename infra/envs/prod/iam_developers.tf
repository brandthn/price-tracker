# IAM — Coéquipiers développeurs.
# Pour ajouter/retirer un dev : éditer `developer_members` → apply.

variable "developer_members" {
  description = "Emails des coéquipiers développeurs (préfixés `user:`). Email utilisé par `gcloud auth login`."
  type        = list(string)
  default = [
    "user:giorgioesgi@gmail.com",
    "user:lomaty99@gmail.com",
  ]
}

locals {
  developer_project_roles = [
    # BigQuery — édition données + lancement queries
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",

    # Cloud SQL — connexion via cloud-sql-proxy (mdp via Secret Manager)
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",

    # Artifact Registry — push images
    "roles/artifactregistry.writer",

    # Cloud Run — déployer révisions
    "roles/run.developer",
    # Indispensable avec run.developer : "act as" les SAs runtime au deploy.
    # N'autorise PAS la création/modification de bindings IAM.
    "roles/iam.serviceAccountUser",

    # Secret Manager — lire valeurs + ajouter versions (rotations)
    "roles/secretmanager.secretAccessor",
    "roles/secretmanager.viewer",
    "roles/secretmanager.secretVersionAdder",

    # Vertex AI — Gemini, embeddings
    "roles/aiplatform.user",

    # Firebase — Auth + FCM en mode développeur
    "roles/firebase.developAdmin",

    # Monitoring + Logs
    "roles/monitoring.editor",
    "roles/logging.viewer",
  ]

  developer_bindings = {
    for pair in setproduct(local.developer_project_roles, var.developer_members) :
    "${pair[0]}__${pair[1]}" => { role = pair[0], member = pair[1] }
  }

  developer_members_set = toset(var.developer_members)
}

resource "google_project_iam_member" "developers" {
  for_each = local.developer_bindings
  project  = var.project_id
  role     = each.value.role
  member   = each.value.member
}

# Buckets data — R/W bronze+silver, lecture seule models
resource "google_storage_bucket_iam_member" "developers_bronze_rw" {
  for_each = local.developer_members_set
  bucket   = module.bucket_bronze.name
  role     = "roles/storage.objectUser"
  member   = each.value
}

resource "google_storage_bucket_iam_member" "developers_silver_rw" {
  for_each = local.developer_members_set
  bucket   = module.bucket_silver.name
  role     = "roles/storage.objectUser"
  member   = each.value
}

resource "google_storage_bucket_iam_member" "developers_models_ro" {
  for_each = local.developer_members_set
  bucket   = module.bucket_models.name
  role     = "roles/storage.objectViewer"
  member   = each.value
}

# tf-state — R/W pour `terraform apply` en local
resource "google_storage_bucket_iam_member" "developers_tfstate_rw" {
  for_each = local.developer_members_set
  bucket   = var.tf_state_bucket
  role     = "roles/storage.objectUser"
  member   = each.value
}
