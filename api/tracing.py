"""OpenTelemetry tracing setup for Google Cloud Trace."""

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.resourcedetector.gcp import GoogleCloudResourceDetector
from opentelemetry.propagators.cloud_trace import CloudTraceFormatPropagator
from opentelemetry import propagate


def setup_tracing():
    """Set up OpenTelemetry tracing with Google Cloud Trace."""
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]

    # Detect GCP resource information
    gcp_resource_detector = GoogleCloudResourceDetector()
    resource = gcp_resource_detector.detect()

    # Merge with service-specific attributes
    resource = resource.merge(
        Resource.create(
            {
                "service.name": "songbook-generator-api",
                "service.version": "0.1.0",
            }
        )
    )

    # Create tracer provider with sampling
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(1.0),  # Sample all traces for now
    )

    # Add Cloud Trace exporter
    cloud_trace_exporter = CloudTraceSpanExporter(project_id=project_id)
    span_processor = BatchSpanProcessor(cloud_trace_exporter)
    tracer_provider.add_span_processor(span_processor)

    # Set the tracer provider
    trace.set_tracer_provider(tracer_provider)

    # Set up Cloud Trace propagator
    propagate.set_global_textmap(CloudTraceFormatPropagator())


def get_tracer(name: str):
    """Get a tracer instance."""
    return trace.get_tracer(name)
