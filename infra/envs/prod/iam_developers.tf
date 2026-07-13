# IAM devs de l'equipe. ajouter/retirer : editer developer_members.

variable "developer_members" {
  description = "Emails devs (prefixe user:)."
  type        = list(string)
  default = [
    "user:giorgioesgi@gmail.com",
    "user:lomaty99@gmail.com",
    "user:tongnia.chatelain@gmail.com"
  ]
}

locals {
  developer_project_roles = [
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",
    "roles/artifactregistry.writer",
    "roles/run.developer",
    "roles/iam.serviceAccountUser",
    "roles/compute.instanceAdmin",
    "roles/secretmanager.secretAccessor",
    "roles/secretmanager.viewer",
    "roles/secretmanager.secretVersionAdder",
    "roles/aiplatform.user",
    "roles/firebase.developAdmin",
    "roles/pubsub.admin",
    "roles/cloudbuild.builds.editor",
    "roles/cloudscheduler.admin",
    "roles/serviceusage.serviceUsageConsumer",
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

# buckets: rw bronze+silver, ro models
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

# tf-state rw
resource "google_storage_bucket_iam_member" "developers_tfstate_rw" {
  for_each = local.developer_members_set
  bucket   = var.tf_state_bucket
  role     = "roles/storage.objectUser"
  member   = each.value
}
