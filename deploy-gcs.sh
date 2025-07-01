# Resources created on GCS for reference
# TODO: migrate to e.g. Terraform
# https://github.com/jjst/songbook-generator/issues/6
set -euo pipefail

echo "1. Enabling required APIs…"
gcloud services enable \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  --project="${PROJECT}"

echo "2. Creating Pub/Sub topic ${TOPIC}…"
gcloud pubsub topics create "${TOPIC}" \
  --project="${PROJECT}" || echo "Topic may already exist, continuing…"

echo "3. Initializing Firestore in Native mode (region=${REGION})…"
gcloud firestore databases create \
  --project="${PROJECT}" \
  --locatoin="${REGION}" \
  --type=firestore-native || echo "Firestore DB may already exist, continuing…"

echo "4. Creating GCS bucket gs://${CDN_BUCKET} in ${REGION}…"
gsutil mb \
  -p "${PROJECT}" \
  -l "${REGION}" \
  "gs://${CDN_BUCKET}" || echo "Bucket may already exist, continuing…"

echo "5. Granting IAM roles to ${SA}…"

# Pub/Sub: allow publishing and subscribing
gcloud pubsub topics add-iam-policy-binding "projects/${PROJECT}/topics/${TOPIC}" \
  --member="serviceAccount:${SA}" \
  --role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/pubsub.subscriber"

# Firestore read/write
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/datastore.user"

# (Optional) if you plan on building indexes dynamically
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/datastore.indexAdmin"

# Storage: allow uploading objects
gsutil iam ch \
  serviceAccount:${SA}:objectCreator \
  "gs://${CDN_BUCKET}"

# (Optional) if you ever need delete/overwrite rights
# gsutil iam ch \
#   serviceAccount:${SA}:objectAdmin \
#   "gs://${CDN_BUCKET}"

echo "6. (Optional) Grant Service Account Token Creator for push subscriptions…"
gcloud iam service-accounts add-iam-policy-binding "${SA}" \
  --member="serviceAccount:${SA}" \
  --role="roles/iam.serviceAccountTokenCreator" || echo "Already bound, continuing…"

echo "✔ All done. 🎉"
