# cloud sql postgres 15, private ip only, zonal, deletion_protection + IAM auth on
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

  password_secret_id = module.secrets.secret_ids["${var.name_prefix}-cloudsql-password"]

  labels = merge(var.labels, { component = "cloud-sql" })
}
