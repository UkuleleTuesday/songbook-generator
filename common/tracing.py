"""OpenTelemetry tracing setup for Google Cloud Trace."""

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

import google.auth
import google.auth.transport.grpc
import google.auth.transport.requests
import grpc
from google.auth.transport.grpc import AuthMetadataPlugin

def setup_tracing():
    # Retrieve and store Google application-default credentials
    credentials, project_id = google.auth.default()
    # Request used to refresh credentials upon expiry
    request = google.auth.transport.requests.Request()

    # Supply the request and credentials to AuthMetadataPlugin
    # AuthMeatadataPlugin inserts credentials into each request
    auth_metadata_plugin = AuthMetadataPlugin(
        credentials=credentials, request=request
    )

    # Initialize gRPC channel credentials using the AuthMetadataPlugin
    channel_creds = grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(),
        grpc.metadata_call_credentials(auth_metadata_plugin),
    )

    resource = Resource.create(
        attributes={
            # Use the PID as the service.instance.id to avoid duplicate timeseries
            # from different Gunicorn worker processes.
            SERVICE_INSTANCE_ID: f"worker-{os.getpid()}",
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
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    if not project_id:
        # Return OpenTelemetry's built-in no-op tracer for local development
        return trace.NoOpTracer()

    return trace.get_tracer(name)
