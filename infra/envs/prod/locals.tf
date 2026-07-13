locals {
  backend_sa    = module.iam.service_accounts["backend"].member
  worker_sa     = module.iam.service_accounts["worker"].member
  gh_actions_sa = module.iam.service_accounts["gh-actions"].member
  frontend_sa   = module.iam.service_accounts["frontend"].member

  # bronze/silver : nearline @30d, delete @90d, rotation versions @90d
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
      action_type                = "Delete"
      days_since_noncurrent_time = 90
      with_state                 = "ARCHIVED"
    },
  ]

  # models : garde la version courante, rotate les anciennes
  models_lifecycle = [
    {
      action_type                = "Delete"
      days_since_noncurrent_time = 90
      with_state                 = "ARCHIVED"
    },
  ]
}
