import os
import json
import base64
import tempfile
from pdf import generate_songbook
import functions_framework
from google.cloud import firestore, storage
from flask import abort
import traceback

# Initialized at cold start
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
FIRESTORE_COLLECTION = os.environ["FIRESTORE_COLLECTION"]
GCS_CDN_BUCKET = os.environ["GCS_CDN_BUCKET"]
GCS_WORKER_CACHE_BUCKET = os.environ["GCS_WORKER_CACHE_BUCKET"]

db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
cdn_bucket = storage_client.bucket(GCS_CDN_BUCKET)
cache_bucket = storage_client.bucket(GCS_WORKER_CACHE_BUCKET)


@functions_framework.cloud_event
def main(cloud_event):
    # 1) Decode Pub/Sub message
    envelope = cloud_event.data
    if "message" not in envelope:
        abort(400, "No Pub/Sub message received")
    msg = envelope["message"]

    data_payload = base64.b64decode(msg["data"]).decode("utf-8")
    evt = json.loads(data_payload)
    job_id = evt["job_id"]
    params = evt["params"]

    job_ref = db.collection(FIRESTORE_COLLECTION).document(job_id)

    # 2) Mark RUNNING
    job_ref.update({"status": "RUNNING", "started_at": firestore.SERVER_TIMESTAMP})

    try:
        source_folders = params["source_folders"]
        cover_file_id = params.get("cover_file_id")
        limit = params.get("limit")

        # 3) Generate into a temp file
        out_path = tempfile.mktemp(suffix=".pdf")
        generate_songbook(source_folders, out_path, limit, cover_file_id)

        # 4) Upload to GCS
        blob = cdn_bucket.blob(f"{job_id}/songbook.pdf")
        blob.upload_from_filename(out_path, content_type="application/pdf")
        result_url = blob.public_url  # or use signed URL if you need auth

        # 5) Update Firestore to COMPLETED
        job_ref.update(
            {
                "status": "COMPLETED",
                "completed_at": firestore.SERVER_TIMESTAMP,
                "result_url": result_url,
            }
        )
    except Exception:
        # on any failure, mark FAILED
        job_ref.update(
            {
                "status": "FAILED",
                "completed_at": firestore.SERVER_TIMESTAMP,
            }
        )
        print(f"Job failed: {job_id}")
        print(traceback.format_exc())
