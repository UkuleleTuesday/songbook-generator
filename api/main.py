import os
import json
import uuid
import functions_framework
from flask import make_response
from google.cloud import pubsub_v1, firestore

# Initialize clients once at cold start
PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
PUBSUB_TOPIC = os.environ["PUBSUB_TOPIC"]
FIRESTORE_COLLECTION = os.environ["FIRESTORE_COLLECTION"]

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)
db = firestore.Client()


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def handle_post(req):
    payload = req.get_json(silent=True) or {}
    job_id = uuid.uuid4().hex

    # 1) Create Firestore job doc
    from datetime import datetime, timedelta

    job_doc = {
        "status": "QUEUED",
        "created_at": firestore.SERVER_TIMESTAMP,
        "expire_at": datetime.utcnow() + timedelta(minutes=20),
        "params": payload,
    }
    db.collection(FIRESTORE_COLLECTION).document(job_id).set(job_doc)

    # 2) Publish Pub/Sub event
    message = {"job_id": job_id, "params": payload}
    publisher.publish(topic_path, json.dumps(message).encode("utf-8"))

    # 3) Return job ID
    body = json.dumps({"job_id": job_id, "status": "queued"})
    return make_response(
        (body, 200, {**_cors_headers(), "Content-Type": "application/json"})
    )


def handle_get_job(job_id):
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(job_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        body = json.dumps({"error": "job not found", "job_id": job_id})
        return make_response(
            (body, 404, {**_cors_headers(), "Content-Type": "application/json"})
        )

    data = snapshot.to_dict()
    response = {
        "job_id": job_id,
        "status": data.get("status", "").lower(),
    }
    if "result_url" in data:
        response["result_url"] = data["result_url"]
    if "created_at" in data:
        ts = data["created_at"]
        try:
            response["created_at"] = ts.isoformat()
        except Exception:
            pass

    body = json.dumps(response)
    return make_response(
        (body, 200, {**_cors_headers(), "Content-Type": "application/json"})
    )


@functions_framework.http
def main(req):
    # CORS preflight
    if req.method == "OPTIONS":
        return ("", 204, _cors_headers())

    # Echo env for debug
    for k, v in os.environ.items():
        print(f"{k}={v}")

    # POST to enqueue new job
    if req.method == "POST" and req.path == "/":
        return handle_post(req)

    # GET healthcheck at root
    if req.method == "GET" and req.path == "/":
        return make_response(("OK", 200, _cors_headers()))

    # GET job status at /{job_id}
    if req.method == "GET":
        # strip leading slash
        job_id = req.path.lstrip("/")
        if job_id:
            return handle_get_job(job_id)

    return make_response(("Method Not Allowed", 405, _cors_headers()))
