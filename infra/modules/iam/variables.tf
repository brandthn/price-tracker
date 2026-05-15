variable "project_id" {
  description = "GCP project ID hosting the service accounts."
  type        = string
}

variable "name_prefix" {
  description = "Resource name prefix (e.g. prt-prod). Each SA is named <name_prefix>-<role>-sa."
  type        = string
  default     = "prt-prod"
}

variable "service_accounts" {
  description = "Map of role name => SA spec. Key is the short role (e.g. backend, worker), used to build the SA account_id <name_prefix>-<key>-sa (must stay <= 30 chars). project_roles are bound at the project level on this SA."
  type = map(object({
    display_name  = string
    description   = string
    project_roles = list(string)
  }))
}
