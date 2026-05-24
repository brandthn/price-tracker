# Cloud Scheduler jobs — déclenche les 4 workers batch quotidiennement.
#
# Chronologie volontairement échelonnée — chaque job consomme la donnée du
# précédent :
#   03h UTC : ingestion (HuggingFace Open Prices → BQ Silver)
#   04h UTC : off       (OpenFoodFacts → catalogue produits + embeddings)
#   05h UTC : indices   (Laspeyres → BQ Gold)
#   07h UTC : alertes   (push FCM ; 2h de marge après indices pour absorber
#                        un retard éventuel)
#
# Toutes les invocations passent un OIDC token signé par worker-sa.
# Cloud Run vérifie côté serveur :
#   1. La signature (clé publique Google)
#   2. Le claim `aud` == URL exacte du service Cloud Run
#   3. La SA dans `iss` a roles/run.invoker (binding fait dans cloud_run.tf)

module "cloud_scheduler_jobs" {
  source = "../../modules/cloud_scheduler"

  project_id = var.project_id
  region     = var.region

  jobs = {
    "${var.name_prefix}-trigger-ingestion" = {
      schedule                   = "0 3 * * *"
      target_url                 = module.run_worker_ingestion.uri
      target_path                = "/run"
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "Phase 6.1 — pull du snapshot HuggingFace open-prices puis load BQ Silver."
    }
    "${var.name_prefix}-trigger-off" = {
      schedule                   = "0 4 * * *"
      target_url                 = module.run_worker_off.uri
      target_path                = "/run"
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "Phase 6.2 — enrichissement EAN via OpenFoodFacts + embeddings Vertex AI."
    }
    "${var.name_prefix}-trigger-indices" = {
      schedule                   = "0 5 * * *"
      target_url                 = module.run_worker_indices.uri
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "Phase 9.1 — calcul indice Laspeyres + détection anomalies → BQ Gold."
    }
    "${var.name_prefix}-trigger-alertes" = {
      schedule                   = "0 7 * * *"
      target_url                 = module.run_worker_alertes.uri
      oidc_service_account_email = module.iam.emails["worker"]
      description                = "Phase 9.2 — push FCM sur les produits en hausse pour chaque user."
    }
  }

  # Sans ce depends_on Terraform peut créer un job avant que le service agent
  # Scheduler n'ait son droit `serviceAccountTokenCreator` → le job est créé
  # mais échoue à l'exécution. Ordre explicite = pas de race au premier apply.
  depends_on = [
    google_service_account_iam_member.scheduler_token_creator_on_worker,
    google_cloud_run_v2_service_iam_member.worker_sa_invoker,
  ]
}
