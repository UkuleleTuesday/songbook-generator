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


@functions_framework.http
def main(req):
    # CORS preflight handler
    if req.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
        return ("", 204, headers)

    # Echo env for debug
    for k, v in os.environ.items():
        print(f"{k}={v}")

    headers = {"Access-Control-Allow-Origin": "*"}

    # GET healthcheck
    if req.method == "GET":
        return make_response(("OK", 200, headers))

    # POST: enqueue a new job
    if req.method == "POST":
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
            (body, 200, {**headers, "Content-Type": "application/json"})
        )

    # Fallback
    return make_response(("Method Not Allowed", 405, headers))
