resource "google_storage_bucket" "bronze" {
  name                        = "${var.bucket_prefix}-bronze"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
}

resource "google_storage_bucket" "signals" {
  name                        = "${var.bucket_prefix}-signals"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.bucket_prefix}-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
}
