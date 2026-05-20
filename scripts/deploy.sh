#!/usr/bin/env bash
set -euo pipefail
# Build & push des images Docker puis instructions pour activer Cloud Run dans Terraform.
# Prérequis : gcloud auth configure-docker, projet GCP configuré.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT_ID:?Définir GCP_PROJECT_ID}"
REGION="${GCP_REGION:-europe-west9}"
REPO="${ARTIFACT_REPOSITORY:-open-prices}"
TAG="${IMAGE_TAG:-latest}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

echo "Build context : ${ROOT}"
for w in worker_ingestion worker_off worker_indices worker_alertes; do
  img="${REGISTRY}/${w}:${TAG}"
  echo ">>> docker build -f ${w}/Dockerfile -t ${img} ."
  docker build -f "${w}/Dockerfile" -t "${img}" .
  docker push "${img}"
done

echo ""
echo "Images poussées. Ensuite :"
echo "  cd terraform && terraform apply -var=project_id=${PROJECT} -var=create_cloud_run_services=true"
