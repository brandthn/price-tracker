# IAM additionnel pour `prt-prod-backend-sa` (Phase 7).
#
# Les rôles projet / dataset / bucket / secret sont déjà bindés ailleurs :
#  - locals.tf : SA member alias
#  - main.tf : project roles (logging, monitoring, cloudsql.client, bigquery.jobUser, ...)
#  - bigquery.tf : dataViewer sur prt_prod_silver/gold/ml
#  - storage.tf : objectAdmin bronze + objectViewer silver
#  - artifact_registry.tf : reader
#  - secret_manager.tf : secretAccessor sur cloudsql-password
#
# Ce fichier ajoute uniquement la self-impersonation requise pour signer des
# URLs GCS V4 sans clé JSON (org policy `iam.disableServiceAccountKeyCreation`).
#
# Mécanisme : `Blob.generate_signed_url(service_account_email=..., access_token=...)`
# délègue la signature à l'IAM Credentials API (`projects.serviceAccounts.signBlob`).
# Pour que l'API accepte, le caller (backend-sa attaché à Cloud Run via ADC) doit
# avoir `roles/iam.serviceAccountTokenCreator` sur la SA cible — ici lui-même.
#
# Référence officielle : https://cloud.google.com/storage/docs/access-control/signed-urls#impersonation
resource "google_service_account_iam_member" "backend_self_impersonation" {
  service_account_id = module.iam.service_accounts["backend"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.backend_sa
}
