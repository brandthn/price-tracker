# VPC privée pour PriceTracker.
# Cloud Run accède à Cloud SQL (private IP, Phase 4) via Direct VPC egress :
# le service Cloud Run est attaché directement au subnet `primary` (config
# `network_interfaces` dans le module cloud_run de la Phase 5). Pas de
# Serverless VPC Connector — supprimé après l'échec récurrent de health check
# sur ce projet + Direct VPC egress est l'approche recommandée par Google
# depuis 2024 (GA), 0 $/mois vs ~10 $/mois pour un connector.
resource "google_compute_network" "vpc" {
  name                    = var.vpc_name
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "PriceTracker VPC — hosts Cloud SQL private IP. Cloud Run attaches via Direct VPC egress."
}

resource "google_compute_subnetwork" "primary" {
  name                     = var.subnet_name
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

# --- Private Services Access (peering pour Cloud SQL private IP) ----------
resource "google_compute_global_address" "psa_range" {
  name          = var.psa_range_name
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = var.psa_range_address
  prefix_length = var.psa_range_prefix_length
  network       = google_compute_network.vpc.id
  description   = "Range reserved for Google-managed services (Cloud SQL, etc.) peering."
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
}
