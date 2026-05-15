terraform {
  backend "gcs" {
    bucket = "price-tracker-prod-01-tf-state"
    prefix = "envs/prod"
  }
}
