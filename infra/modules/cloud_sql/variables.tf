variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the Cloud SQL instance."
  type        = string
}

variable "instance_name" {
  description = "Cloud SQL instance name (e.g. prt-prod-sql-main)."
  type        = string
}

variable "database_version" {
  description = "Postgres major version. Must support pgvector (>=15)."
  type        = string
  default     = "POSTGRES_15"
}

variable "tier" {
  description = "Machine tier."
  type        = string
  default     = "db-g1-small"
}

variable "availability_type" {
  description = "ZONAL (HA off) or REGIONAL (HA on, ~2x cost)."
  type        = string
  default     = "ZONAL"
  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.availability_type)
    error_message = "availability_type must be ZONAL or REGIONAL."
  }
}

variable "disk_size_gb" {
  description = "Initial disk size (GB). Auto-resize is enabled."
  type        = number
  default     = 10
}

variable "disk_type" {
  description = "PD_SSD (default) or PD_HDD."
  type        = string
  default     = "PD_SSD"
}

variable "vpc_self_link" {
  description = "VPC self_link to attach the instance to (private IP only)."
  type        = string
}

variable "psa_dependency" {
  description = "google_service_networking_connection resource — passed as object so the instance waits for the peering."
  type        = any
}

variable "db_name" {
  description = "Application database name."
  type        = string
}

variable "db_user" {
  description = "Application Postgres user (will have cloudsqlsuperuser privileges by default on Cloud SQL)."
  type        = string
}

variable "password_secret_id" {
  description = "Existing Secret Manager secret ID to push the generated app user password into (a new version v1 is added)."
  type        = string
}

variable "deletion_protection" {
  description = "Block `terraform destroy` of the instance. Edit and re-apply to lower before destroying."
  type        = bool
  default     = true
}

variable "backup_start_time" {
  description = "Daily backup start time, UTC (HH:MM)."
  type        = string
  default     = "03:00"
}

variable "maintenance_day" {
  description = "Maintenance window day (1=Mon … 7=Sun)."
  type        = number
  default     = 7
}

variable "maintenance_hour" {
  description = "Maintenance window hour (0-23, UTC)."
  type        = number
  default     = 4
}

variable "iam_authentication" {
  description = "Enable Cloud SQL IAM database authentication (lets SAs auth without password via Cloud SQL Auth Proxy)."
  type        = bool
  default     = true
}

variable "labels" {
  description = "Labels applied to the instance."
  type        = map(string)
  default     = {}
}
