# VPC + subnet + Private Services Access (peering Cloud SQL) + Serverless VPC
# Connector pour le egress Cloud Run vers la SQL en private IP.
module "network" {
  source = "../../modules/network"

  project_id = var.project_id
  region     = var.region
  # Defaults : prt-vpc / prt-subnet-ew1 / prt-vpc-connector / prt-psa-range
}
