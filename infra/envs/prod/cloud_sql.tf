# Cloud SQL Postgres 15 — instance applicative principale.
# - Private IP only (pas d'exposition Internet). Cloud Run s'y connectera via
#   Direct VPC egress (Phase 5) + Cloud SQL Auth Proxy intégré.
# - HA OFF (ZONAL) : projet école, RTO ~10 min acceptable. Pour passer en HA :
#   `availability_type = "REGIONAL"` (coût ×2).
# - deletion_protection ON : éviter un destroy accidentel. Pour détruire,
#   éditer à false, apply, puis destroy.
# - IAM database authentication ON : permet aux SAs Cloud Run de se connecter
#   sans mot de passe via Cloud SQL Auth Proxy (Phase 7).
module "cloud_sql_main" {
  source = "../../modules/cloud_sql"

  project_id = var.project_id
  region     = var.region

  instance_name       = "${var.name_prefix}-sql-main"
  database_version    = "POSTGRES_15"
  tier                = "db-g1-small"
  availability_type   = "ZONAL"
  disk_size_gb        = 10
  disk_type           = "PD_SSD"
  deletion_protection = true
  iam_authentication  = true

  vpc_self_link  = module.network.vpc_self_link
  psa_dependency = module.network.psa_connection

  db_name = "price_tracker"
  db_user = "pt_app"

  # Pousse le mot de passe généré dans le secret pré-créé en Phase 2.
  password_secret_id = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]

  labels = merge(var.labels, { component = "cloud-sql" })
}
