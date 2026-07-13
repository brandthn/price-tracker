provider "google" {
  project = var.project_id
  region  = var.region
}

# google-beta : uniquement pour google_project_service_identity
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# tf-state bucket (cree a la main puis importe)
resource "google_storage_bucket" "tf_state" {
  name                        = var.tf_state_bucket
  project                     = var.project_id
  location                    = "EU"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      num_newer_versions = 30
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      days_since_noncurrent_time = 90
      with_state                 = "ARCHIVED"
    }
  }

  labels = merge(var.labels, { component = "tf-state" })

  lifecycle {
    prevent_destroy = true
  }
}

module "iam" {
  source = "../../modules/iam"

  project_id  = var.project_id
  name_prefix = var.name_prefix

  service_accounts = {
    terraform = {
      display_name = "Terraform runner SA"
      description  = "Impersonne pour terraform apply."
      project_roles = [
        "roles/editor",
        "roles/resourcemanager.projectIamAdmin",
        "roles/iam.serviceAccountAdmin",
        "roles/iam.serviceAccountUser",
        "roles/storage.admin",
        "roles/serviceusage.serviceUsageAdmin",
      ]
    }
    backend = {
      display_name = "Backend API SA (FastAPI on Cloud Run)"
      description  = "Runtime prt-prod-backend."
      project_roles = [
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/cloudtrace.agent",
        "roles/cloudsql.client",
        "roles/cloudsql.instanceUser",
        "roles/bigquery.jobUser",
      ]
    }
    worker = {
      display_name = "Workers SA (OCR, ingestion, OFF, indices, alertes)"
      description  = "SA partage pour tous les workers Cloud Run."
      project_roles = [
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/cloudtrace.agent",
        "roles/cloudsql.client",
        "roles/cloudsql.instanceUser",
        "roles/bigquery.jobUser",
        "roles/aiplatform.user",
      ]
    }
    gh-actions = {
      display_name = "GitHub Actions deployer SA"
      description  = "Impersonne par GitHub Actions via WIF."
      project_roles = []
    }
    frontend = {
      display_name = "Frontend Next.js SA (Cloud Run)"
      description  = "Runtime prt-prod-frontend. Aucun acces data."
      project_roles = [
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/cloudtrace.agent",
      ]
    }
  }
}
