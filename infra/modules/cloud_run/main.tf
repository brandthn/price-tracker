resource "google_cloud_run_v2_service" "this" {
  name     = var.name
  project  = var.project_id
  location = var.region
  ingress  = var.ingress
  labels   = var.labels

  template {
    service_account       = var.service_account_email
    execution_environment = var.execution_environment
    timeout               = "${var.timeout_seconds}s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Direct VPC egress — gen2 only. Skipped if vpc_subnet is null
    # (e.g. for a Cloud Run that doesn't need private resources).
    dynamic "vpc_access" {
      for_each = var.vpc_subnet == null ? [] : [1]
      content {
        network_interfaces {
          subnetwork = var.vpc_subnet
        }
        egress = var.vpc_egress
      }
    }

    containers {
      image = var.image

      ports {
        container_port = var.container_port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = true
        startup_cpu_boost = false
      }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }
    }
  }
}

# Optionnel : exposer le service publiquement (utile uniquement pour le
# backend en attendant le Load Balancer de la Phase 7). Les workers gardent
# ce flag à false → seules les SAs autorisées via run.invoker peuvent invoquer.
resource "google_cloud_run_v2_service_iam_member" "all_users" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = google_cloud_run_v2_service.this.project
  location = google_cloud_run_v2_service.this.location
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
