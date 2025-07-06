"""Tests for the tracing module."""

import os
from unittest.mock import patch, MagicMock


@patch("tracing.metrics.set_meter_provider")
@patch("tracing.events.set_event_logger_provider")
@patch("tracing.logs.set_logger_provider")
@patch("tracing.trace.set_tracer_provider")
@patch("tracing.MeterProvider")
@patch("tracing.PeriodicExportingMetricReader")
@patch("tracing.OTLPMetricExporter")
@patch("tracing.EventLoggerProvider")
@patch("tracing.LoggerProvider")
@patch("tracing.BatchLogRecordProcessor")
@patch("tracing.OTLPLogExporter")
@patch("tracing.TracerProvider")
@patch("tracing.BatchSpanProcessor")
@patch("tracing.OTLPSpanExporter")
@patch("tracing.Resource")
def test_setup_tracing_success(
    mock_resource_class,
    mock_otlp_span_exporter_class,
    mock_batch_span_processor_class,
    mock_tracer_provider_class,
    mock_otlp_log_exporter_class,
    mock_batch_log_processor_class,
    mock_logger_provider_class,
    mock_event_logger_provider_class,
    mock_otlp_metric_exporter_class,
    mock_periodic_metric_reader_class,
    mock_meter_provider_class,
    mock_set_tracer_provider,
    mock_set_logger_provider,
    mock_set_event_logger_provider,
    mock_set_meter_provider,
):
    """Test that setup_tracing configures all components correctly."""
    # Mock the resource
    mock_resource = MagicMock()
    mock_resource_class.create.return_value = mock_resource

    # Mock the tracer provider
    mock_tracer_provider = MagicMock()
    mock_tracer_provider_class.return_value = mock_tracer_provider

    # Mock the span exporter and processor
    mock_span_exporter = MagicMock()
    mock_span_processor = MagicMock()
    mock_otlp_span_exporter_class.return_value = mock_span_exporter
    mock_batch_span_processor_class.return_value = mock_span_processor

    # Mock the log exporter, processor, and provider
    mock_log_exporter = MagicMock()
    mock_log_processor = MagicMock()
    mock_logger_provider = MagicMock()
    mock_otlp_log_exporter_class.return_value = mock_log_exporter
    mock_batch_log_processor_class.return_value = mock_log_processor
    mock_logger_provider_class.return_value = mock_logger_provider

    # Mock the event logger provider
    mock_event_logger_provider = MagicMock()
    mock_event_logger_provider_class.return_value = mock_event_logger_provider

    # Mock the metric exporter, reader, and provider
    mock_metric_exporter = MagicMock()
    mock_metric_reader = MagicMock()
    mock_meter_provider = MagicMock()
    mock_otlp_metric_exporter_class.return_value = mock_metric_exporter
    mock_periodic_metric_reader_class.return_value = mock_metric_reader
    mock_meter_provider_class.return_value = mock_meter_provider

    # Import and call setup_tracing
    from tracing import setup_tracing

    setup_tracing()

    # Verify resource was created with SERVICE_INSTANCE_ID
    mock_resource_class.create.assert_called_once()
    call_kwargs = mock_resource_class.create.call_args[1]
    assert "attributes" in call_kwargs
    assert "service.instance.id" in call_kwargs["attributes"]
    assert call_kwargs["attributes"]["service.instance.id"].startswith("worker-")

    # Verify tracer provider was created with resource
    mock_tracer_provider_class.assert_called_once_with(resource=mock_resource)

    # Verify span exporter and processor were created
    mock_otlp_span_exporter_class.assert_called_once()
    mock_batch_span_processor_class.assert_called_once_with(mock_span_exporter)

    # Verify processor was added to tracer provider
    mock_tracer_provider.add_span_processor.assert_called_once_with(mock_span_processor)

    # Verify tracer provider was set globally
    mock_set_tracer_provider.assert_called_once_with(mock_tracer_provider)

    # Verify logger provider was created and configured
    mock_logger_provider_class.assert_called_once_with(resource=mock_resource)
    mock_otlp_log_exporter_class.assert_called_once()
    mock_batch_log_processor_class.assert_called_once_with(mock_log_exporter)
    mock_logger_provider.add_log_record_processor.assert_called_once_with(mock_log_processor)
    mock_set_logger_provider.assert_called_once_with(mock_logger_provider)

    # Verify event logger provider was created
    mock_event_logger_provider_class.assert_called_once_with(mock_logger_provider)
    mock_set_event_logger_provider.assert_called_once_with(mock_event_logger_provider)

    # Verify meter provider was created and configured
    mock_otlp_metric_exporter_class.assert_called_once()
    mock_periodic_metric_reader_class.assert_called_once_with(mock_metric_exporter)
    mock_meter_provider_class.assert_called_once_with(
        metric_readers=[mock_metric_reader], resource=mock_resource
    )
    mock_set_meter_provider.assert_called_once_with(mock_meter_provider)


def test_setup_tracing_no_exceptions():
    """Test that setup_tracing runs without exceptions."""
    from tracing import setup_tracing

    # Should not raise any exceptions
    setup_tracing()


@patch("tracing.trace.get_tracer")
def test_get_tracer_with_project_id(mock_get_tracer):
    """Test that get_tracer calls the OpenTelemetry get_tracer function when project ID is available."""
    mock_tracer = MagicMock()
    mock_get_tracer.return_value = mock_tracer

    with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project"}):
        from tracing import get_tracer

        result = get_tracer("test-service")

        mock_get_tracer.assert_called_once_with("test-service")
        assert result == mock_tracer


def test_get_tracer_no_project_id():
    """Test that get_tracer returns a NoOpTracer when project ID is missing."""
    with patch.dict(os.environ, {}, clear=True):
        from tracing import get_tracer
        from opentelemetry.trace import NoOpTracer

        result = get_tracer("test-service")

        # Should return a NoOpTracer instance
        assert isinstance(result, NoOpTracer)


def test_get_tracer_returns_callable():
    """Test that get_tracer returns something that looks like a tracer."""
    from tracing import get_tracer

    tracer = get_tracer("test-service")

    # Should have tracer methods
    assert hasattr(tracer, "start_span") or hasattr(tracer, "start_as_current_span")
