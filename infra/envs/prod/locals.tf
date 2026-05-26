locals {
  # SA members convenience accessors (used by storage/AR/secrets IAM bindings).
  backend_sa    = module.iam.service_accounts["backend"].member
  worker_sa     = module.iam.service_accounts["worker"].member
  gh_actions_sa = module.iam.service_accounts["gh-actions"].member
  frontend_sa   = module.iam.service_accounts["frontend"].member

  # Default lifecycle rules for the data lake buckets (bronze, silver).
  # STANDARD -> NEARLINE @ 30d, delete @ 90d. Versioning rotation @ 90d.
  data_lake_lifecycle = [
    {
      action_type          = "SetStorageClass"
      action_storage_class = "NEARLINE"
      age                  = 30
    },
    {
      action_type = "Delete"
      age         = 90
    },
    {
      # Garbage-collect old object versions after 90 days (only if versioning is on).
      action_type                = "Delete"
      days_since_noncurrent_time = 90
      with_state                 = "ARCHIVED"
    },
  ]

  # Models bucket: keep current model indefinitely, rotate old versions.
  models_lifecycle = [
    {
      action_type                = "Delete"
      days_since_noncurrent_time = 90
      with_state                 = "ARCHIVED"
    },
  ]
}
