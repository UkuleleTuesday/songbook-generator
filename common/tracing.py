"""OpenTelemetry tracing setup for Google Cloud Trace."""

import os
from opentelemetry import _events as events
from opentelemetry import _logs as logs
from opentelemetry import metrics, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, Resource
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._events import EventLoggerProvider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader


def setup_tracing():
    resource = Resource.create(
        attributes={
            # Use the PID as the service.instance.id to avoid duplicate timeseries
            # from different Gunicorn worker processes.
            SERVICE_INSTANCE_ID: f"worker-{os.getpid()}",
        }
    )

    # Set up OpenTelemetry Python SDK
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    logs.set_logger_provider(logger_provider)

    event_logger_provider = EventLoggerProvider(logger_provider)
    events.set_event_logger_provider(event_logger_provider)

    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(metric_readers=[reader], resource=resource)
    metrics.set_meter_provider(meter_provider)


def get_tracer(name: str):
    """Get a tracer instance."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    if not project_id:
        # Return OpenTelemetry's built-in no-op tracer for local development
        return trace.NoOpTracer()

    return trace.get_tracer(name)
