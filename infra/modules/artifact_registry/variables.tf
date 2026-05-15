variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "location" {
  description = "Repository location (Google region for Docker repos)."
  type        = string
}

variable "repository_id" {
  description = "Repository ID."
  type        = string
  default     = "prt-prod-docker"
}

variable "description" {
  description = "Repository description."
  type        = string
  default     = "PriceTracker Docker images (backend + workers)."
}

variable "labels" {
  description = "Labels applied to the repository."
  type        = map(string)
  default     = {}
}

variable "readers" {
  description = "SA members (`serviceAccount:email`) granted `roles/artifactregistry.reader`."
  type        = list(string)
  default     = []
}

variable "writers" {
  description = "SA members granted `roles/artifactregistry.writer` (push images, e.g. GitHub Actions)."
  type        = list(string)
  default     = []
}

variable "cleanup_keep_count" {
  description = "Number of recent versions to keep per package (set to 0 to disable cleanup policy)."
  type        = number
  default     = 10
}
