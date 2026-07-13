# vpc + subnet + PSA (peering cloud sql) + connector egress cloud run
module "network" {
  source = "../../modules/network"

  project_id = var.project_id
  region     = var.region
}
