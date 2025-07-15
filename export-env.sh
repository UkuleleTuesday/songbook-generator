#!/bin/bash
#
# Usage: source export-env.sh
#
# This script exports environment variables from the .env file.
# It should be sourced to affect the current shell session.

export GCP_PROJECT_ID=songbook-generator
export GCP_REGION=europe-west1
export PUBSUB_TOPIC=songbook-jobs
export CACHE_REFRESH_PUBSUB_TOPIC=songbook-cache-refresh-jobs
export CACHE_REFRESH_SCHEDULE="*/15 * * * *"
export FIRESTORE_COLLECTION=jobs
export GCS_CDN_BUCKET=songbook-generator-cdn-europe-west1
export GCS_WORKER_CACHE_BUCKET=songbook-generator-cache-europe-west1
export WORKER_FUNCTION_NAME=songbook-generator-worker
export API_FUNCTION_NAME=songbook-generator-api
export MERGER_FUNCTION_NAME=songbook-generator-merger
export SA=993670465212-compute@developer.gserviceaccount.com
export GENERATOR_ADD_PAGE_NUMBERS=true

echo "Environment variables exported."
