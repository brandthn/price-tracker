# backend-sa self-impersonation : signer des URLs GCS V4 sans cle JSON
resource "google_service_account_iam_member" "backend_self_impersonation" {
  service_account_id = module.iam.service_accounts["backend"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.backend_sa
}
