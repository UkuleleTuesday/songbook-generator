import os
import json
import uuid
from datetime import datetime, timedelta, UTC
from typing import Optional, Annotated
from google.cloud import pubsub_v1, firestore
from loguru import logger

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from vellox import Vellox

# Initialize tracing
from ..common.tracing import get_tracer, setup_tracing
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


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


def initialize_tracing():
    """Initialize tracing as a global dependency."""
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    service_name = os.environ.get("K_SERVICE", "songbook-generator-api")
    os.environ["GCP_PROJECT_ID"] = project_id
    setup_tracing(service_name)


def get_tracer_dependency():
    """Dependency to get OpenTelemetry tracer."""
    return get_tracer(__name__)


def get_firestore_client():
    """Dependency to get Firestore client."""
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    return firestore.Client(project=project_id)


def get_pubsub_publisher():
    """Dependency to get Pub/Sub publisher."""
    return pubsub_v1.PublisherClient()


def get_pubsub_topic_path(
    publisher: Annotated[pubsub_v1.PublisherClient, Depends(get_pubsub_publisher)],
):
    """Dependency to get Pub/Sub topic path."""
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    pubsub_topic = os.environ["PUBSUB_TOPIC"]
    return publisher.topic_path(project_id, pubsub_topic)


def _create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Songbook Generator API",
        description="API for generating songbooks from Google Drive sources",
        version="1.0.0",
        dependencies=[Depends(initialize_tracing)],
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # Try to instrument with OpenTelemetry if available
    try:
        FastAPIInstrumentor.instrument_app(app)
    except (ImportError, AttributeError):
        # If instrumentation fails, continue without it
        pass

    return app


# Create the app instance at module level
app = _create_app()


@app.post("/", response_model=JobResponse, status_code=200)
async def create_job(
    job_request: JobRequest,
    request: Request,
    tracer: Annotated[object, Depends(get_tracer_dependency)],
    db: Annotated[firestore.Client, Depends(get_firestore_client)],
    publisher: Annotated[pubsub_v1.PublisherClient, Depends(get_pubsub_publisher)],
    topic_path: Annotated[str, Depends(get_pubsub_topic_path)],
):
    """Create a new songbook generation job."""
    with tracer.start_as_current_span("create_job") as span:
        # Convert the pydantic model to dict, filtering out None values
        payload = {k: v for k, v in job_request.model_dump().items() if v is not None}
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
            firestore_collection = os.environ["FIRESTORE_COLLECTION"]
            db.collection(firestore_collection).document(job_id).set(job_doc)
            firestore_span.set_attribute("firestore.collection", firestore_collection)
            firestore_span.set_attribute("firestore.document_id", job_id)

        # Publish Pub/Sub message
        with tracer.start_as_current_span("publish_pubsub_message") as pubsub_span:
            message = {"job_id": job_id, "params": payload}
            serialized_message = json.dumps(message)
            logger.info(f"Publishing message to Pub/Sub topic: {topic_path}")
            future = publisher.publish(topic_path, serialized_message.encode("utf-8"))
            future.result()
            pubsub_span.set_attribute("pubsub.topic", topic_path)
            pubsub_span.set_attribute("pubsub.message_size", len(serialized_message))

        span.set_attribute("response.status_code", 200)
        return JobResponse(job_id=job_id, status="queued")


@app.get("/{job_id}", response_model=JobStatusResponse, status_code=200)
async def get_job_status(
    job_id: str,
    tracer: Annotated[object, Depends(get_tracer_dependency)],
    db: Annotated[firestore.Client, Depends(get_firestore_client)],
):
    """Get the status of a job."""
    with tracer.start_as_current_span("get_job_status") as span:
        span.set_attribute("job_id", job_id)
        logger.info(f"Fetching Firestore document for job ID: {job_id}")

        with tracer.start_as_current_span("fetch_firestore_document") as firestore_span:
            firestore_collection = os.environ["FIRESTORE_COLLECTION"]
            doc_ref = db.collection(firestore_collection).document(job_id)
            snapshot = doc_ref.get()
            firestore_span.set_attribute("firestore.collection", firestore_collection)
            firestore_span.set_attribute("firestore.document_id", job_id)
            firestore_span.set_attribute("firestore.document_exists", snapshot.exists)

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


def api_main(req):
    """Main entry point for Cloud Functions compatibility."""
    vellox = Vellox(app=app, lifespan="off")
    return vellox(req)
