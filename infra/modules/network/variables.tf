variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the subnet."
  type        = string
}

variable "vpc_name" {
  description = "VPC name."
  type        = string
  default     = "prt-vpc"
}

variable "subnet_name" {
  description = "Primary subnet name. Used by Cloud Run via Direct VPC egress (Phase 5+)."
  type        = string
  default     = "prt-subnet-ew1"
}

variable "subnet_cidr" {
  description = "Primary subnet CIDR. Must be >= /26 to support Cloud Run Direct VPC egress at scale."
  type        = string
  default     = "10.10.0.0/24"
}

variable "psa_range_name" {
  description = "Name of the global address range used for Private Services Access (Cloud SQL peering)."
  type        = string
  default     = "prt-psa-range"
}

variable "psa_range_address" {
  description = "Starting address of the PSA range (e.g. 10.20.0.0)."
  type        = string
  default     = "10.20.0.0"
}

variable "psa_range_prefix_length" {
  description = "Prefix length of the PSA range (Google recommends /16)."
  type        = number
  default     = 16
}
