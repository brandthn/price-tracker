provider "google" {
  project = var.project_id
  region  = var.region
}

# google-beta : utilisé uniquement par `google_project_service_identity`
# (cf. service_agents.tf). Le reste du code reste sur le provider stable.
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# --- tf-state bucket -------------------------------------------------------
# Créé manuellement en Phase 0 (chicken-and-egg : Terraform a besoin d'un
# backend pour stocker son state). On l'adopte ensuite sous Terraform via
# `terraform import google_storage_bucket.tf_state price-tracker-prod-01-tf-state`.
# Cf. infra/README.md §Import.
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

# --- Service Accounts ------------------------------------------------------
# Rôles volontairement minimaux pour Phase 1. Les phases suivantes ajouteront
# les rôles spécifiques (Cloud SQL Client, BQ, Secret Accessor, etc.) au fur
# et à mesure que les ressources sont créées.
module "iam" {
  source = "../../modules/iam"

  project_id  = var.project_id
  name_prefix = var.name_prefix

  service_accounts = {
    terraform = {
      display_name = "Terraform runner SA"
      description  = "Impersonné par les humains/CI pour exécuter `terraform apply`."
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
      description  = "Runtime du service Cloud Run prt-prod-backend (Phase 7)."
      project_roles = [
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/cloudtrace.agent",
        # Phase 4 — accès Cloud SQL via Cloud SQL Auth Proxy / connecteur, et BQ
        # pour la lecture des indices observatoire. Le rôle `instanceUser` est
        # requis si on s'authentifie via IAM database authentication.
        "roles/cloudsql.client",
        "roles/cloudsql.instanceUser",
        "roles/bigquery.jobUser",
      ]
    }
    worker = {
      display_name = "Workers SA (OCR, ingestion, OFF, indices, alertes)"
      description  = "SA partagé pour tous les workers Cloud Run (Phases 6/8/9)."
      project_roles = [
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/cloudtrace.agent",
        # Phase 4 — workers ingestion/OFF/indices ont besoin de Cloud SQL +
        # BQ jobs. Vertex AI est ajouté pour la génération des embeddings
        # produit dans le worker OFF (Phase 6.2).
        "roles/cloudsql.client",
        "roles/cloudsql.instanceUser",
        "roles/bigquery.jobUser",
        "roles/aiplatform.user",
      ]
    }
    gh-actions = {
      display_name = "GitHub Actions deployer SA"
      description  = "Impersonné par GitHub Actions via Workload Identity Federation (Phase 3)."
      # Aucun rôle projet en Phase 1. Phase 3 ajoutera le binding WIF + le droit
      # d'impersonner prt-prod-terraform-sa pour les changements infra.
      project_roles = []
    }
  }
}
