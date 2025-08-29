#!/usr/bin/env bash
set -euo pipefail

# Script to cleanup preview environment resources
# Usage: ./cleanup-preview-resources.sh <environment_suffix>
# Example: ./cleanup-preview-resources.sh -pr-123

if [ $# -ne 1 ]; then
    echo "Usage: $0 <environment_suffix>"
    echo "Example: $0 -pr-123"
    exit 1
fi

ENVIRONMENT_SUFFIX="$1"

# Load .env if present, exporting all variables
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "Cleaning up preview environment resources with suffix: ${ENVIRONMENT_SUFFIX}"

# Apply suffix to resource names
PREVIEW_PUBSUB_TOPIC="${PUBSUB_TOPIC}${ENVIRONMENT_SUFFIX}"
PREVIEW_CACHE_REFRESH_PUBSUB_TOPIC="${CACHE_REFRESH_PUBSUB_TOPIC}${ENVIRONMENT_SUFFIX}"
PREVIEW_FIRESTORE_COLLECTION="${FIRESTORE_COLLECTION}${ENVIRONMENT_SUFFIX}"
PREVIEW_GCS_CDN_BUCKET="${GCS_CDN_BUCKET}${ENVIRONMENT_SUFFIX}"
PREVIEW_GCS_WORKER_CACHE_BUCKET="${GCS_WORKER_CACHE_BUCKET}${ENVIRONMENT_SUFFIX}"
PREVIEW_GCS_SONGBOOKS_BUCKET="${GCS_SONGBOOKS_BUCKET}${ENVIRONMENT_SUFFIX}"
PREVIEW_GCS_SONGBOOKS_LOGS_BUCKET="${GCS_SONGBOOKS_LOGS_BUCKET}${ENVIRONMENT_SUFFIX}"

echo "Cleanup targets:"
echo "  PUBSUB_TOPIC: ${PREVIEW_PUBSUB_TOPIC}"
echo "  CACHE_REFRESH_PUBSUB_TOPIC: ${PREVIEW_CACHE_REFRESH_PUBSUB_TOPIC}"
echo "  FIRESTORE_COLLECTION: ${PREVIEW_FIRESTORE_COLLECTION}"
echo "  GCS_CDN_BUCKET: ${PREVIEW_GCS_CDN_BUCKET}"
echo "  GCS_WORKER_CACHE_BUCKET: ${PREVIEW_GCS_WORKER_CACHE_BUCKET}"
echo "  GCS_SONGBOOKS_BUCKET: ${PREVIEW_GCS_SONGBOOKS_BUCKET}"
echo "  GCS_SONGBOOKS_LOGS_BUCKET: ${PREVIEW_GCS_SONGBOOKS_LOGS_BUCKET}"

# Delete Pub/Sub topics
echo "1. Deleting Pub/Sub topics…"
if gcloud pubsub topics describe "${PREVIEW_PUBSUB_TOPIC}" --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  echo "Deleting Pub/Sub topic: ${PREVIEW_PUBSUB_TOPIC}"
  gcloud pubsub topics delete "${PREVIEW_PUBSUB_TOPIC}" --project="${GCP_PROJECT_ID}" --quiet
else
  echo "Pub/Sub topic ${PREVIEW_PUBSUB_TOPIC} not found, skipping"
fi

if gcloud pubsub topics describe "${PREVIEW_CACHE_REFRESH_PUBSUB_TOPIC}" --project="${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  echo "Deleting Pub/Sub topic: ${PREVIEW_CACHE_REFRESH_PUBSUB_TOPIC}"
  gcloud pubsub topics delete "${PREVIEW_CACHE_REFRESH_PUBSUB_TOPIC}" --project="${GCP_PROJECT_ID}" --quiet
else
  echo "Pub/Sub topic ${PREVIEW_CACHE_REFRESH_PUBSUB_TOPIC} not found, skipping"
fi

# Delete GCS buckets
echo "2. Deleting GCS buckets…"
for BUCKET in "${PREVIEW_GCS_CDN_BUCKET}" "${PREVIEW_GCS_WORKER_CACHE_BUCKET}" "${PREVIEW_GCS_SONGBOOKS_BUCKET}" "${PREVIEW_GCS_SONGBOOKS_LOGS_BUCKET}"; do
  if gsutil ls -b "gs://${BUCKET}" >/dev/null 2>&1; then
    echo "Deleting GCS bucket: gs://${BUCKET}"
    # Remove all objects first
    gsutil -m rm -r "gs://${BUCKET}/**" || echo "No objects to delete in gs://${BUCKET}"
    # Remove the bucket
    gsutil rb "gs://${BUCKET}"
  else
    echo "GCS bucket gs://${BUCKET} not found, skipping"
  fi
done

# Delete Firestore collection documents
echo "3. Deleting Firestore collection documents…"
# Use gcloud firestore to delete documents in the collection
# Note: This deletes documents but not the collection itself (collections are auto-deleted when empty)
gcloud firestore collections delete "${PREVIEW_FIRESTORE_COLLECTION}" \
  --project="${GCP_PROJECT_ID}" \
  --quiet \
  --async || echo "Firestore collection ${PREVIEW_FIRESTORE_COLLECTION} may not exist or already be empty"

echo "✔ Preview environment cleanup completed for suffix: ${ENVIRONMENT_SUFFIX}"
