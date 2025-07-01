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
    job_doc = {
        "status": "QUEUED",
        "created_at": firestore.SERVER_TIMESTAMP,
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


def handle_get(req):
    job_id = req.args.get("job_id")
    if not job_id:
        body = json.dumps({"error": "missing job_id query parameter"})
        return make_response(
            (body, 400, {**_cors_headers(), "Content-Type": "application/json"})
        )

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
        # Firestore returns a Timestamp; convert to ISO string if present
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

    if req.method == "POST":
        return handle_post(req)

    if req.method == "GET":
        return handle_get(req)

    return make_response(("Method Not Allowed", 405, _cors_headers()))
