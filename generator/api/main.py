import os
import json
import uuid
from datetime import datetime, timedelta
from google.cloud import pubsub_v1, firestore
from loguru import logger

# Initialize tracing
from ..common.tracing import get_tracer, setup_tracing

# Cache for initialized clients to avoid re-initialization on warm starts
_services = None


def _get_services():
    """Initializes and returns services, using a cache for warm starts."""
    global _services
    if _services is not None:
        return _services

    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    service_name = os.environ.get("K_SERVICE", "songbook-generator-api")
    os.environ["GCP_PROJECT_ID"] = project_id
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    pubsub_topic = os.environ["PUBSUB_TOPIC"]
    firestore_collection = os.environ["FIRESTORE_COLLECTION"]
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, pubsub_topic)
    db = firestore.Client(project=project_id)

    _services = {
        "tracer": tracer,
        "db": db,
        "publisher": publisher,
        "topic_path": topic_path,
        "firestore_collection": firestore_collection,
    }
    return _services


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def handle_post(req, services):
    with services["tracer"].start_as_current_span("handle_post") as span:
        logger.info(f"Received POST request with payload: {req.get_data(as_text=True)}")
        payload = req.get_json(silent=True) or {}
        job_id = uuid.uuid4().hex

        span.set_attribute("job_id", job_id)
        span.set_attribute("payload_size", len(json.dumps(payload)))

        # 1) Create Firestore job doc
        with services["tracer"].start_as_current_span(
            "create_firestore_job"
        ) as firestore_span:
            job_doc = {
                "status": "QUEUED",
                "created_at": firestore.SERVER_TIMESTAMP,
                "expire_at": datetime.utcnow() + timedelta(minutes=30),
                "params": payload,
            }
            logger.info(f"Creating Firestore job document with ID: {job_id}")
            services["db"].collection(services["firestore_collection"]).document(
                job_id
            ).set(job_doc)
            firestore_span.set_attribute(
                "firestore.collection", services["firestore_collection"]
            )
            firestore_span.set_attribute("firestore.document_id", job_id)

        # 2) Publish Pub/Sub event
        with services["tracer"].start_as_current_span(
            "publish_pubsub_message"
        ) as pubsub_span:
            message = {"job_id": job_id, "params": payload}
            serialized_message = json.dumps(message)
            logger.info(
                f"Publishing message to Pub/Sub topic: {services['topic_path']}"
            )
            future = services["publisher"].publish(
                services["topic_path"], serialized_message.encode("utf-8")
            )
            future.result()
            pubsub_span.set_attribute("pubsub.topic", os.environ["PUBSUB_TOPIC"])
            pubsub_span.set_attribute("pubsub.message_size", len(serialized_message))

        # 3) Return job ID
        body = json.dumps({"job_id": job_id, "status": "queued"})
        span.set_attribute("response.status_code", 200)
        return (body, 200, {**_cors_headers(), "Content-Type": "application/json"})


def handle_get_job(job_id, services):
    with services["tracer"].start_as_current_span("handle_get_job") as span:
        span.set_attribute("job_id", job_id)

        logger.info(f"Fetching Firestore document for job ID: {job_id}")

        with services["tracer"].start_as_current_span(
            "fetch_firestore_document"
        ) as firestore_span:
            doc_ref = (
                services["db"]
                .collection(services["firestore_collection"])
                .document(job_id)
            )
            snapshot = doc_ref.get()
            firestore_span.set_attribute(
                "firestore.collection", services["firestore_collection"]
            )
            firestore_span.set_attribute("firestore.document_id", job_id)
            firestore_span.set_attribute("firestore.document_exists", snapshot.exists)

        logger.info(f"Firestore document exists: {snapshot.exists}")
        if not snapshot.exists:
            body = json.dumps({"error": "job not found", "job_id": job_id})
            span.set_attribute("response.status_code", 404)
            span.set_attribute("error", "job not found")
            return (body, 404, {**_cors_headers(), "Content-Type": "application/json"})

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
            except AttributeError:
                # ts is not a datetime object, can't be formatted.
                # It is optional in the response, so we can ignore.
                pass

        span.set_attribute("job.status", data.get("status", ""))
        span.set_attribute("response.status_code", 200)
        body = json.dumps(response)
        return (body, 200, {**_cors_headers(), "Content-Type": "application/json"})


def api_main(req):
    services = _get_services()
    with services["tracer"].start_as_current_span("api_main") as span:
        span.set_attribute("http.method", req.method)
        span.set_attribute("http.path", req.path)

        # CORS preflight
        if req.method == "OPTIONS":
            span.set_attribute("request.type", "cors_preflight")
            return ("", 204, _cors_headers())

        # POST to enqueue new job
        if req.method == "POST" and req.path == "/":
            logger.info("Handling POST request at root path")
            span.set_attribute("request.type", "enqueue_job")
            return handle_post(req, services)

        # GET healthcheck at root
        if req.method == "GET" and req.path == "/":
            logger.info("Handling GET healthcheck at root path")
            span.set_attribute("request.type", "healthcheck")
            return ("OK", 200, _cors_headers())

        # GET job status at /{job_id}
        if req.method == "GET":
            # strip leading slash
            job_id = req.path.lstrip("/")
            if job_id:
                logger.info(f"Handling GET request for job ID: {job_id}")
                span.set_attribute("request.type", "get_job_status")
                return handle_get_job(job_id, services)

        logger.error(f"Unhandled request method: {req.method}, path: {req.path}")
        span.set_attribute("request.type", "unhandled")
        span.set_attribute("error", "method not allowed")
        return ("Method Not Allowed", 405, _cors_headers())
