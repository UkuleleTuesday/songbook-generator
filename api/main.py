import os
import json
import uuid
import functions_framework
from datetime import datetime, timedelta
from flask import make_response
from google.cloud import pubsub_v1, firestore

# Initialize tracing
from .tracing import setup_tracing, get_tracer

# Initialize clients once at cold start
PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
PUBSUB_TOPIC = os.environ["PUBSUB_TOPIC"]
FIRESTORE_COLLECTION = os.environ["FIRESTORE_COLLECTION"]

# Set up tracing
setup_tracing()

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)
db = firestore.Client()

# Initialize tracer
tracer = get_tracer(__name__)


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def handle_post(req):
    with tracer.start_as_current_span("handle_post") as span:
        print("Received POST request with payload:", req.get_data(as_text=True))
        payload = req.get_json(silent=True) or {}
        job_id = uuid.uuid4().hex

        span.set_attribute("job_id", job_id)
        span.set_attribute("payload_size", len(json.dumps(payload)))

        # 1) Create Firestore job doc
        with tracer.start_as_current_span("create_firestore_job") as firestore_span:
            job_doc = {
                "status": "QUEUED",
                "created_at": firestore.SERVER_TIMESTAMP,
                "expire_at": datetime.utcnow() + timedelta(minutes=30),
                "params": payload,
            }
            print(f"Creating Firestore job document with ID: {job_id}")
            db.collection(FIRESTORE_COLLECTION).document(job_id).set(job_doc)
            firestore_span.set_attribute("firestore.collection", FIRESTORE_COLLECTION)
            firestore_span.set_attribute("firestore.document_id", job_id)

        # 2) Publish Pub/Sub event
        with tracer.start_as_current_span("publish_pubsub_message") as pubsub_span:
            message = {"job_id": job_id, "params": payload}
            serialized_message = json.dumps(message)
            print(f"Publishing message to Pub/Sub topic: {topic_path}")
            future = publisher.publish(topic_path, serialized_message.encode("utf-8"))
            future.result()
            pubsub_span.set_attribute("pubsub.topic", PUBSUB_TOPIC)
            pubsub_span.set_attribute("pubsub.message_size", len(serialized_message))

        # 3) Return job ID
        body = json.dumps({"job_id": job_id, "status": "queued"})
        span.set_attribute("response.status_code", 200)
        return make_response(
            (body, 200, {**_cors_headers(), "Content-Type": "application/json"})
        )


def handle_get_job(job_id):
    with tracer.start_as_current_span("handle_get_job") as span:
        span.set_attribute("job_id", job_id)

        print(f"Fetching Firestore document for job ID: {job_id}")

        with tracer.start_as_current_span("fetch_firestore_document") as firestore_span:
            doc_ref = db.collection(FIRESTORE_COLLECTION).document(job_id)
            snapshot = doc_ref.get()
            firestore_span.set_attribute("firestore.collection", FIRESTORE_COLLECTION)
            firestore_span.set_attribute("firestore.document_id", job_id)
            firestore_span.set_attribute("firestore.document_exists", snapshot.exists)

        print(f"Firestore document exists: {snapshot.exists}")
        if not snapshot.exists:
            body = json.dumps({"error": "job not found", "job_id": job_id})
            span.set_attribute("response.status_code", 404)
            span.set_attribute("error", "job not found")
            return make_response(
                (body, 404, {**_cors_headers(), "Content-Type": "application/json"})
            )

        data = snapshot.to_dict()
        response = {
            "job_id": job_id,
            "status": data.get("status", "").lower(),
        }

        # Add progress information if available
        if "progress" in data:
            response["progress"] = data["progress"]
            span.set_attribute("job.progress", data["progress"])

        if "last_message" in data:
            response["last_message"] = data["last_message"]

        if "result_url" in data:
            response["result_url"] = data["result_url"]
            span.set_attribute("job.has_result_url", True)
        if "created_at" in data:
            ts = data["created_at"]
            try:
                response["created_at"] = ts.isoformat()
            except Exception:
                pass

        span.set_attribute("job.status", data.get("status", ""))
        span.set_attribute("response.status_code", 200)
        body = json.dumps(response)
        return make_response(
            (body, 200, {**_cors_headers(), "Content-Type": "application/json"})
        )


@functions_framework.http
def main(req):
    with tracer.start_as_current_span("main") as span:
        span.set_attribute("http.method", req.method)
        span.set_attribute("http.path", req.path)

        # CORS preflight
        if req.method == "OPTIONS":
            span.set_attribute("request.type", "cors_preflight")
            return ("", 204, _cors_headers())

        # Echo env for debug
        print("Environment variables:")
        for k, v in os.environ.items():
            print(f"{k}={v}")

        # POST to enqueue new job
        if req.method == "POST" and req.path == "/":
            print("Handling POST request at root path")
            span.set_attribute("request.type", "enqueue_job")
            return handle_post(req)

        # GET healthcheck at root
        if req.method == "GET" and req.path == "/":
            print("Handling GET healthcheck at root path")
            span.set_attribute("request.type", "healthcheck")
            return make_response(("OK", 200, _cors_headers()))

        # GET job status at /{job_id}
        if req.method == "GET":
            # strip leading slash
            job_id = req.path.lstrip("/")
            if job_id:
                print(f"Handling GET request for job ID: {job_id}")
                span.set_attribute("request.type", "get_job_status")
                return handle_get_job(job_id)

        print(f"Unhandled request method: {req.method}, path: {req.path}")
        span.set_attribute("request.type", "unhandled")
        span.set_attribute("error", "method not allowed")
        return make_response(("Method Not Allowed", 405, _cors_headers()))
