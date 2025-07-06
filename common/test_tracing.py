"""Tests for the tracing module."""

import os
from unittest.mock import patch, MagicMock


@patch("tracing.propagate.set_global_textmap")
@patch("tracing.trace.set_tracer_provider")
@patch("tracing.TracerProvider")
@patch("tracing.BatchSpanProcessor")
@patch("tracing.CloudTraceSpanExporter")
@patch("tracing.GoogleCloudResourceDetector")
def test_setup_tracing_success(
    mock_resource_detector_class,
    mock_cloud_trace_exporter_class,
    mock_batch_span_processor_class,
    mock_tracer_provider_class,
    mock_set_tracer_provider,
    mock_set_global_textmap,
):
    """Test that setup_tracing configures all components correctly."""
    # Mock environment
    with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project"}):
        # Mock the resource detector and resource
        mock_resource_detector = MagicMock()
        mock_resource = MagicMock()

        mock_resource_detector_class.return_value = mock_resource_detector
        mock_resource_detector.detect.return_value = mock_resource

        # Mock the tracer provider
        mock_tracer_provider = MagicMock()
        mock_tracer_provider_class.return_value = mock_tracer_provider

        # Mock the exporter and processor
        mock_exporter = MagicMock()
        mock_processor = MagicMock()
        mock_cloud_trace_exporter_class.return_value = mock_exporter
        mock_batch_span_processor_class.return_value = mock_processor

        # Import and call setup_tracing
        from tracing import setup_tracing

        setup_tracing()

        # Verify resource detector was called
        mock_resource_detector_class.assert_called_once()
        mock_resource_detector.detect.assert_called_once()

        # Verify tracer provider was created with correct parameters
        mock_tracer_provider_class.assert_called_once()
        call_kwargs = mock_tracer_provider_class.call_args[1]
        assert call_kwargs["resource"] == mock_resource
        assert call_kwargs["sampler"] is not None

        # Verify exporter was created with project ID
        mock_cloud_trace_exporter_class.assert_called_once_with(
            project_id="test-project"
        )

        # Verify processor was created with exporter
        mock_batch_span_processor_class.assert_called_once_with(mock_exporter)

        # Verify processor was added to tracer provider
        mock_tracer_provider.add_span_processor.assert_called_once_with(mock_processor)

        # Verify tracer provider was set globally
        mock_set_tracer_provider.assert_called_once_with(mock_tracer_provider)

        # Verify propagator was set
        mock_set_global_textmap.assert_called_once()


def test_setup_tracing_missing_project_id(capsys):
    """Test that setup_tracing handles gracefully when project ID is missing."""
    with patch.dict(os.environ, {}, clear=True):
        from tracing import setup_tracing

        # Should not raise an exception, just print a message
        setup_tracing()

        # Verify the expected message was printed
        captured = capsys.readouterr()
        assert (
            "No GOOGLE_CLOUD_PROJECT found, skipping tracing setup"
            in captured.out
        )


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
