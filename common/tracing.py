"""OpenTelemetry tracing setup for Google Cloud Trace."""

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.resourcedetector.gcp_resource_detector import (
    GoogleCloudResourceDetector,
)
from opentelemetry.propagators.cloud_trace_propagator import CloudTraceFormatPropagator
from opentelemetry import propagate


class NoOpTracer:
    """No-op tracer for local development."""
    def start_as_current_span(self, name):
        return NoOpSpan()


class NoOpSpan:
    """No-op span for local development."""
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def set_attribute(self, key, value):
        pass


def setup_tracing(service_name: str):
    """Set up OpenTelemetry tracing with Google Cloud Trace."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    
    if not project_id:
        # Running locally, don't set up tracing
        print(f"No GOOGLE_CLOUD_PROJECT found, skipping tracing setup for {service_name}")
        return

    # Detect GCP resource information
    gcp_resource_detector = GoogleCloudResourceDetector()
    resource = gcp_resource_detector.detect()

    # Merge with service-specific attributes
    resource = resource.merge(
        Resource.create(
            {
                "service.name": service_name,
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
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    
    if not project_id:
        # Return no-op tracer for local development
        return NoOpTracer()
    
    return trace.get_tracer(name)
