import os
import json
import uuid
from datetime import datetime, timedelta, UTC
from typing import Optional
from google.cloud import pubsub_v1, firestore
from loguru import logger

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Initialize tracing
from ..common.tracing import get_tracer, setup_tracing
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Cache for initialized clients to avoid re-initialization on warm starts
_services = None
_app = None


class JobRequest(BaseModel):
    source_folders: Optional[list[str]] = None
    limit: Optional[int] = None
    cover_file_id: Optional[str] = None
    edition: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: Optional[int] = None
    last_message: Optional[str] = None
    result_url: Optional[str] = None
    created_at: Optional[str] = None


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


def _create_fastapi_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Songbook Generator API",
        description="API for generating songbooks from Google Drive sources",
        version="1.0.0",
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # Initialize services for tracing (but don't depend on tracer provider)
    try:
        _get_services()  # Initialize services without assigning to unused variable
        # Try to instrument with OpenTelemetry if available
        FastAPIInstrumentor.instrument_app(app)
    except (ImportError, AttributeError):
        # If instrumentation fails, continue without it
        pass

    @app.get("/", status_code=200)
    async def health_check():
        """Health check endpoint."""
        return "OK"

    @app.post("/", response_model=JobResponse, status_code=200)
    async def create_job(job_request: JobRequest, request: Request):
        """Create a new songbook generation job."""
        services = _get_services()
        tracer = services["tracer"]

        with tracer.start_as_current_span("create_job") as span:
            # Convert the pydantic model to dict, filtering out None values
            payload = {
                k: v for k, v in job_request.model_dump().items() if v is not None
            }
            job_id = uuid.uuid4().hex

            span.set_attribute("job_id", job_id)
            span.set_attribute("payload_size", len(json.dumps(payload)))

            logger.info(f"Creating job {job_id} with payload: {payload}")

            # Create Firestore job document
            with tracer.start_as_current_span("create_firestore_job") as firestore_span:
                job_doc = {
                    "status": "QUEUED",
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "expire_at": datetime.now(UTC) + timedelta(minutes=30),
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

            # Publish Pub/Sub message
            with tracer.start_as_current_span("publish_pubsub_message") as pubsub_span:
                message = {"job_id": job_id, "params": payload}
                serialized_message = json.dumps(message)
                logger.info(
                    f"Publishing message to Pub/Sub topic: {services['topic_path']}"
                )
                future = services["publisher"].publish(
                    services["topic_path"], serialized_message.encode("utf-8")
                )
                future.result()
                pubsub_span.set_attribute("pubsub.topic", services["topic_path"])
                pubsub_span.set_attribute(
                    "pubsub.message_size", len(serialized_message)
                )

            span.set_attribute("response.status_code", 200)
            return JobResponse(job_id=job_id, status="queued")

    @app.get("/{job_id}", response_model=JobStatusResponse, status_code=200)
    async def get_job_status(job_id: str):
        """Get the status of a job."""
        services = _get_services()
        tracer = services["tracer"]

        with tracer.start_as_current_span("get_job_status") as span:
            span.set_attribute("job_id", job_id)
            logger.info(f"Fetching Firestore document for job ID: {job_id}")

            with tracer.start_as_current_span(
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
                firestore_span.set_attribute(
                    "firestore.document_exists", snapshot.exists
                )

            logger.info(f"Firestore document exists: {snapshot.exists}")
            if not snapshot.exists:
                span.set_attribute("response.status_code", 404)
                span.set_attribute("error", "job not found")
                raise HTTPException(
                    status_code=404,
                    detail={"error": "job not found", "job_id": job_id},
                )

            data = snapshot.to_dict()
            response_data = {
                "job_id": job_id,
                "status": data.get("status", "").lower(),
            }

            # Add optional fields if they exist
            if "progress" in data:
                response_data["progress"] = data["progress"]
                span.set_attribute("job.progress", data["progress"])

            if "last_message" in data:
                response_data["last_message"] = data["last_message"]

            if "result_url" in data:
                response_data["result_url"] = data["result_url"]
                span.set_attribute("job.has_result_url", True)

            if "created_at" in data:
                ts = data["created_at"]
                try:
                    response_data["created_at"] = ts.isoformat()
                except AttributeError:
                    # ts is not a datetime object, ignore
                    pass

            span.set_attribute("job.status", data.get("status", ""))
            span.set_attribute("response.status_code", 200)

            return JobStatusResponse(**response_data)

    return app


def get_app() -> FastAPI:
    """Get or create the FastAPI application instance."""
    global _app
    if _app is None:
        _app = _create_fastapi_app()
    return _app


def api_main(req):
    """Main entry point for Cloud Functions compatibility."""
    # For Cloud Functions, we need to handle the request using the FastAPI app
    app = get_app()

    # Convert Cloud Functions request to ASGI format
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # Map the Cloud Functions request to a proper HTTP request
        method = req.method
        path = req.path
        headers = {}

        # Safely get headers if they exist
        try:
            if hasattr(req, "headers") and req.headers:
                headers = dict(req.headers) if hasattr(req.headers, "keys") else {}
        except (TypeError, AttributeError):
            headers = {}

        # Get request data
        if method == "POST":
            try:
                json_data = req.get_json(silent=True)
            except (AttributeError, ValueError):
                json_data = None
        else:
            json_data = None

        # Make the request through TestClient
        if method == "POST":
            response = client.post(path, json=json_data, headers=headers)
        elif method == "GET":
            response = client.get(path, headers=headers)
        elif method == "OPTIONS":
            response = client.options(path, headers=headers)
        else:
            response = client.get("/nonexistent", headers=headers)  # Will return 404

        # Convert response to Cloud Functions format
        response_headers = dict(response.headers)

        # Ensure CORS headers are present
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
        response_headers.update(cors_headers)

        return (response.text, response.status_code, response_headers)
