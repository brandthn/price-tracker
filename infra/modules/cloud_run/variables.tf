variable "project_id" {
  description = "GCP project ID hosting the Cloud Run service."
  type        = string
}

variable "region" {
  description = "Region for the Cloud Run service. Must match the region of the VPC subnet and (when invoked by Cloud Scheduler) the Scheduler job."
  type        = string
}

variable "name" {
  description = "Cloud Run service name (e.g. prt-prod-backend)."
  type        = string
}

variable "image" {
  description = "Container image URI (Artifact Registry path or public image)."
  type        = string
}

variable "service_account_email" {
  description = "Runtime service account email attached to the service. Tokens issued via ADC come from this SA."
  type        = string
}

variable "env" {
  description = "Plain (non-secret) environment variables injected into the container."
  type        = map(string)
  default     = {}
}

variable "secret_env" {
  description = <<-EOT
    Secret-backed environment variables. Map of ENV_VAR_NAME => { secret = <secret_id>, version = <version or "latest"> }.
    The secret must already exist in Secret Manager and the runtime SA must have roles/secretmanager.secretAccessor on it.
  EOT
  type = map(object({
    secret  = string
    version = optional(string, "latest")
  }))
  default = {}
}

variable "min_instances" {
  description = "Minimum number of instances. 0 = scale-to-zero (no cost when idle, cold start on first request)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of instances (cost guard rail)."
  type        = number
  default     = 3
}

variable "cpu" {
  description = "vCPU limit per instance. Values: '1', '2', '4', '8' (gen2 execution env)."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory limit per instance (e.g. '512Mi', '1Gi', '2Gi')."
  type        = string
  default     = "512Mi"
}

variable "container_port" {
  description = "Port the container listens on. Cloud Run forwards HTTPS traffic to this port."
  type        = number
  default     = 8080
}

variable "timeout_seconds" {
  description = "Per-request timeout in seconds (max 3600 for gen2)."
  type        = number
  default     = 300
}

variable "vpc_subnet" {
  description = "Subnet name (or full self_link) the service attaches to via Direct VPC egress. Set to null to disable VPC attachment."
  type        = string
  default     = null
}

variable "vpc_egress" {
  description = "Traffic routed through the VPC. PRIVATE_RANGES_ONLY = only RFC1918 traffic goes through VPC (recommended). ALL_TRAFFIC = everything (more costly, only needed if a Cloud NAT enforces egress)."
  type        = string
  default     = "PRIVATE_RANGES_ONLY"
  validation {
    condition     = contains(["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC"], var.vpc_egress)
    error_message = "vpc_egress must be PRIVATE_RANGES_ONLY or ALL_TRAFFIC."
  }
}

variable "ingress" {
  description = "Who can reach the service. INGRESS_TRAFFIC_ALL = public. INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER = internal + LB + GCP services (Cloud Scheduler, Pub/Sub push). INGRESS_TRAFFIC_INTERNAL_ONLY = only VPC."
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  validation {
    condition = contains([
      "INGRESS_TRAFFIC_ALL",
      "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
      "INGRESS_TRAFFIC_INTERNAL_ONLY",
    ], var.ingress)
    error_message = "ingress must be one of INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER, INGRESS_TRAFFIC_INTERNAL_ONLY."
  }
}

variable "execution_environment" {
  description = "Cloud Run gen1 or gen2. Gen2 required for Direct VPC egress."
  type        = string
  default     = "EXECUTION_ENVIRONMENT_GEN2"
}

variable "labels" {
  description = "Labels applied to the service (app/env/managed_by/component)."
  type        = map(string)
  default     = {}
}

variable "allow_unauthenticated" {
  description = "If true, grants run.invoker to allUsers (public service). Use only for the backend with ingress=ALL. Workers must keep this false."
  type        = bool
  default     = false
}
