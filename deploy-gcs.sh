#!/usr/bin/env bash
set -euo pipefail

# Load .env if present, exporting all variables
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Support for preview environments
# If ENVIRONMENT_SUFFIX is set, append it to resource names
ENVIRONMENT_SUFFIX="${ENVIRONMENT_SUFFIX:-}"
if [ -n "$ENVIRONMENT_SUFFIX" ]; then
  echo "Setting up preview environment with suffix: ${ENVIRONMENT_SUFFIX}"

  # Append suffix to resource names
  PUBSUB_TOPIC="${PUBSUB_TOPIC}${ENVIRONMENT_SUFFIX}"
  CACHE_REFRESH_PUBSUB_TOPIC="${CACHE_REFRESH_PUBSUB_TOPIC}${ENVIRONMENT_SUFFIX}"
  FIRESTORE_COLLECTION="${FIRESTORE_COLLECTION}${ENVIRONMENT_SUFFIX}"
  GCS_CDN_BUCKET="${GCS_CDN_BUCKET}${ENVIRONMENT_SUFFIX}"
  GCS_WORKER_CACHE_BUCKET="${GCS_WORKER_CACHE_BUCKET}${ENVIRONMENT_SUFFIX}"
  GCS_SONGBOOKS_BUCKET="${GCS_SONGBOOKS_BUCKET}${ENVIRONMENT_SUFFIX}"
  GCS_SONGBOOKS_LOGS_BUCKET="${GCS_SONGBOOKS_LOGS_BUCKET}${ENVIRONMENT_SUFFIX}"

  echo "Preview environment resources:"
  echo "  PUBSUB_TOPIC: ${PUBSUB_TOPIC}"
  echo "  CACHE_REFRESH_PUBSUB_TOPIC: ${CACHE_REFRESH_PUBSUB_TOPIC}"
  echo "  FIRESTORE_COLLECTION: ${FIRESTORE_COLLECTION}"
  echo "  GCS_CDN_BUCKET: ${GCS_CDN_BUCKET}"
  echo "  GCS_WORKER_CACHE_BUCKET: ${GCS_WORKER_CACHE_BUCKET}"
  echo "  GCS_SONGBOOKS_BUCKET: ${GCS_SONGBOOKS_BUCKET}"
  echo "  GCS_SONGBOOKS_LOGS_BUCKET: ${GCS_SONGBOOKS_LOGS_BUCKET}"
fi

echo "1. Enabling required APIs…"
# Skip API enablement in CI or for preview environments since services are already enabled
if [ -z "${CI}" ] && [ -z "$ENVIRONMENT_SUFFIX" ]; then
  gcloud services enable \
    pubsub.googleapis.com \
    cloudscheduler.googleapis.com \
    firestore.googleapis.com \
    storage.googleapis.com \
    eventarc.googleapis.com \
    telemetry.googleapis.com \
    monitoring.googleapis.com \
    logging.googleapis.com \
    --project="${GCP_PROJECT_ID}"
else
  echo "Skipping API enablement (running in CI or preview environment - APIs should already be enabled)"
fi

echo "2. Creating Pub/Sub topic ${PUBSUB_TOPIC}…"
gcloud pubsub topics create "${PUBSUB_TOPIC}" \
  --project="${GCP_PROJECT_ID}" || echo "Topic may already exist, continuing…"

echo "2b. Creating Pub/Sub topic ${CACHE_REFRESH_PUBSUB_TOPIC}…"
gcloud pubsub topics create "${CACHE_REFRESH_PUBSUB_TOPIC}" \
  --project="${GCP_PROJECT_ID}" || echo "Topic may already exist, continuing…"

echo "3. Initializing Firestore in Native mode (region=${GCP_REGION})…"
gcloud firestore databases create \
  --project="${GCP_PROJECT_ID}" \
  --location="${GCP_REGION}" \
  --type=firestore-native || echo "Firestore DB may already exist, continuing…"

echo "3b. Setting up ttl on Firestore..."
gcloud firestore fields ttls update "expire_at" \
  --project="${GCP_PROJECT_ID}" \
  --collection-group="${FIRESTORE_COLLECTION}" \
  --enable-ttl \
  --async # This can take a while...

echo "4. Creating GCS buckets in ${GCP_REGION}…"
# CDN bucket
gsutil mb \
  -p "${GCP_PROJECT_ID}" \
  -l "${GCP_REGION}" \
  "gs://${GCS_CDN_BUCKET}" || echo "CDN bucket may already exist, continuing…"
# Worker cache bucket
gsutil mb \
  -p "${GCP_PROJECT_ID}" \
  -l "${GCP_REGION}" \
  "gs://${GCS_WORKER_CACHE_BUCKET}" || echo "Worker cache bucket may already exist, continuing…"
# Public songbook buckets
gsutil mb \
  -p "${GCP_PROJECT_ID}" \
  -l "${GCP_REGION}" \
  "gs://${GCS_SONGBOOKS_BUCKET}" || echo "Songbooks bucket may already exist, continuing…"
# Songbook logs bucket
gsutil mb \
  -p "${GCP_PROJECT_ID}" \
  -l "${GCP_REGION}" \
  "gs://${GCS_SONGBOOKS_LOGS_BUCKET}" || echo "Songbook logs bucket may already exist, continuing…"

# For preview environments, bootstrap by copying data from live buckets
if [ -n "$ENVIRONMENT_SUFFIX" ]; then
  # Define source buckets (live environment)
  LIVE_CDN_BUCKET="${GCS_CDN_BUCKET%$ENVIRONMENT_SUFFIX}"
  LIVE_WORKER_CACHE_BUCKET="${GCS_WORKER_CACHE_BUCKET%$ENVIRONMENT_SUFFIX}"
  LIVE_SONGBOOKS_BUCKET="${GCS_SONGBOOKS_BUCKET%$ENVIRONMENT_SUFFIX}"

  echo "4a. Bootstrapping preview environment from live buckets…"

  # Copy CDN bucket contents if source exists
  if gsutil ls -b "gs://${LIVE_CDN_BUCKET}" >/dev/null 2>&1; then
    echo "Copying CDN bucket contents from gs://${LIVE_CDN_BUCKET} to gs://${GCS_CDN_BUCKET}"
    gsutil -m cp -r "gs://${LIVE_CDN_BUCKET}/**" "gs://${GCS_CDN_BUCKET}/" || echo "CDN bucket copy failed or no content to copy"
  else
    echo "Live CDN bucket gs://${LIVE_CDN_BUCKET} not found, skipping copy"
  fi

  # Copy worker cache bucket contents if source exists
  if gsutil ls -b "gs://${LIVE_WORKER_CACHE_BUCKET}" >/dev/null 2>&1; then
    echo "Copying worker cache bucket contents from gs://${LIVE_WORKER_CACHE_BUCKET} to gs://${GCS_WORKER_CACHE_BUCKET}"
    gsutil -m cp -r "gs://${LIVE_WORKER_CACHE_BUCKET}/**" "gs://${GCS_WORKER_CACHE_BUCKET}/" || echo "Worker cache bucket copy failed or no content to copy"
  else
    echo "Live worker cache bucket gs://${LIVE_WORKER_CACHE_BUCKET} not found, skipping copy"
  fi

  # Copy songbooks bucket contents if source exists
  if gsutil ls -b "gs://${LIVE_SONGBOOKS_BUCKET}" >/dev/null 2>&1; then
    echo "Copying songbooks bucket contents from gs://${LIVE_SONGBOOKS_BUCKET} to gs://${GCS_SONGBOOKS_BUCKET}"
    gsutil -m cp -r "gs://${LIVE_SONGBOOKS_BUCKET}/**" "gs://${GCS_SONGBOOKS_BUCKET}/" || echo "Songbooks bucket copy failed or no content to copy"
  else
    echo "Live songbooks bucket gs://${LIVE_SONGBOOKS_BUCKET} not found, skipping copy"
  fi
fi

echo "4b. Setting bucket permissions"
gsutil uniformbucketlevelaccess set on gs://$GCS_CDN_BUCKET
gsutil iam ch allUsers:roles/storage.objectViewer gs://$GCS_CDN_BUCKET
gsutil uniformbucketlevelaccess set on gs://$GCS_WORKER_CACHE_BUCKET
gsutil iam ch allUsers:roles/storage.objectViewer gs://$GCS_WORKER_CACHE_BUCKET
gsutil uniformbucketlevelaccess set on gs://$GCS_SONGBOOKS_BUCKET
gsutil iam ch allUsers:roles/storage.objectViewer gs://$GCS_SONGBOOKS_BUCKET


echo "4c. Setting up access logs for ${GCS_SONGBOOKS_BUCKET} bucket"
gcloud storage buckets add-iam-policy-binding "gs://${GCS_SONGBOOKS_LOGS_BUCKET}" --member=group:cloud-storage-analytics@google.com --role=roles/storage.objectCreator
gcloud storage buckets update "gs://${GCS_SONGBOOKS_BUCKET}" --log-bucket="gs://${GCS_SONGBOOKS_LOGS_BUCKET}"


echo "5. Setting lifecycle policies (90-day TTL) on buckets…"
# prepare lifecycle config
LIFECYCLE_JSON=$(mktemp)
cat >"${LIFECYCLE_JSON}" <<EOF
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"age": 90}
    }
  ]
}
EOF

gsutil lifecycle set "${LIFECYCLE_JSON}" "gs://${GCS_CDN_BUCKET}"
gsutil lifecycle set "${LIFECYCLE_JSON}" "gs://${GCS_WORKER_CACHE_BUCKET}"
rm "${LIFECYCLE_JSON}"

echo "6. Granting IAM roles to ${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}…"
# Pub/Sub: allow publishing and subscribing
gcloud pubsub topics add-iam-policy-binding "projects/${GCP_PROJECT_ID}/topics/${PUBSUB_TOPIC}" \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/pubsub.subscriber"

# Firestore read/write
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/datastore.user"

# (Optional) if you plan on building indexes dynamically
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/datastore.indexAdmin"

# Storage: allow uploading objects to CDN bucket
gsutil iam ch \
  "serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}:objectAdmin" \
  "gs://${GCS_CDN_BUCKET}"

# Storage: allow uploading objects to worker cache bucket
gsutil iam ch \
  "serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}:objectAdmin" \
  "gs://${GCS_WORKER_CACHE_BUCKET}"

# Storage: allow uploading objects to songbooks bucket
gsutil iam ch \
  "serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}:objectAdmin" \
  "gs://${GCS_SONGBOOKS_BUCKET}"
gsutil iam ch \
  "serviceAccount:cloud-run-deployer@${GCP_PROJECT_ID}.iam.gserviceaccount.com:objectAdmin" \
  "gs://${GCS_SONGBOOKS_BUCKET}"

echo "7. (Optional) Grant Service Account Token Creator for push subscriptions…"
gcloud iam service-accounts add-iam-policy-binding "${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/iam.serviceAccountTokenCreator" || echo "Already bound, continuing…"

echo "8. Make sure service account can write observability stuff"
# Traces Writer
gcloud projects add-iam-policy-binding ${GCP_PROJECT_ID} \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/telemetry.tracesWriter"

# Logs Writer
gcloud projects add-iam-policy-binding ${GCP_PROJECT_ID} \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/logging.logWriter"

# Monitoring Metric Writer
gcloud projects add-iam-policy-binding ${GCP_PROJECT_ID} \
  --member="serviceAccount:${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
  --role="roles/monitoring.metricWriter"

echo "9. Set up cron schedule for cache refresh"
# Skip cron setup for preview environments to avoid conflicts
if [ -z "$ENVIRONMENT_SUFFIX" ]; then
  # Create a JSON array of folder IDs from the comma-separated env var.
  # e.g., "id1,id2" becomes '{"source_folders":["id1","id2"]}'
  # shellcheck disable=SC2016
  PAYLOAD_JSON='{"source_folders":["'$(echo "${GDRIVE_SONG_SHEETS_FOLDER_IDS}" | sed 's/,/","/g')'"]}'

  gcloud scheduler jobs create http trigger-merger-job \
    --schedule="*/15 * * * *" \
    --time-zone="Europe/Dublin" \
    --uri="$(gcloud run services describe "${MERGER_FUNCTION_NAME}" --region "${GCP_REGION}" --format="value(uri)")" \
    --http-method=POST \
    --oidc-service-account-email="${SONGBOOK_GENERATOR_SERVICE_ACCOUNT}" \
    --message-body="${PAYLOAD_JSON}" \
    --location="${GCP_REGION}" \
    --description="Triggers the PDF merger and cache sync for songbooks."
else
  echo "Skipping cron job setup for preview environment"
fi

echo "✔ All done. 🎉"
