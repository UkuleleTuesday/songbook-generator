"""OpenTelemetry tracing setup for Google Cloud Trace."""

import os
from opentelemetry import trace
from opentelemetry.trace import NoOpTracerProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

import google.auth
import google.auth.transport.grpc
import google.auth.transport.requests
import grpc
from google.auth.transport.grpc import AuthMetadataPlugin


from .config import get_settings


def setup_tracing(service_name):
    settings = get_settings()

    # If tracing is disabled via config, use the NoOp provider.
    if not settings.tracing.enabled:
        trace.set_tracer_provider(NoOpTracerProvider())
        return

    # Retrieve and store Google application-default credentials
    try:
        credentials, project_id = google.auth.default()
    except google.auth.exceptions.DefaultCredentialsError:
        # We're likely running locally without gcloud auth. Fall back to NoOp.
        trace.set_tracer_provider(NoOpTracerProvider())
        return
    # Request used to refresh credentials upon expiry
    request = google.auth.transport.requests.Request()

    # Supply the request and credentials to AuthMetadataPlugin
    # AuthMeatadataPlugin inserts credentials into each request
    auth_metadata_plugin = AuthMetadataPlugin(credentials=credentials, request=request)

    # Initialize gRPC channel credentials using the AuthMetadataPlugin
    channel_creds = grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(),
        grpc.metadata_call_credentials(auth_metadata_plugin),
    )

    resource = Resource.create(
        attributes={
            SERVICE_NAME: service_name,
            # Use the PID as the service.instance.id to avoid duplicate timeseries
            # from different Gunicorn worker processes.
            SERVICE_INSTANCE_ID: f"worker-{os.getpid()}",
            # Include deploy version for easier identification across environments
            "service.version": os.environ.get("DEPLOY_VERSION", "unknown"),
        }
    )

    # Set up OpenTelemetry Python SDK
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(credentials=channel_creds))
    )
    trace.set_tracer_provider(tracer_provider)


def get_tracer(name: str):
    """Get a tracer instance."""
    settings = get_settings()

    if not settings.tracing.enabled:
        # Return OpenTelemetry's built-in no-op tracer if disabled.
        return trace.NoOpTracer()

    return trace.get_tracer(name)
