"""Tests for the tracing module."""

import os
import pytest
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
        mock_merged_resource = MagicMock()

        mock_resource_detector_class.return_value = mock_resource_detector
        mock_resource_detector.detect.return_value = mock_resource
        mock_resource.merge.return_value = mock_merged_resource

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

        setup_tracing("test-service")

        # Verify resource detector was called
        mock_resource_detector_class.assert_called_once()
        mock_resource_detector.detect.assert_called_once()

        # Verify resource was merged with service attributes
        mock_resource.merge.assert_called_once()
        merge_call_args = mock_resource.merge.call_args[0][0]
        assert "service.name" in merge_call_args.attributes
        assert merge_call_args.attributes["service.name"] == "test-service"
        assert merge_call_args.attributes["service.version"] == "0.1.0"

        # Verify tracer provider was created with correct parameters
        mock_tracer_provider_class.assert_called_once()
        call_kwargs = mock_tracer_provider_class.call_args[1]
        assert call_kwargs["resource"] == mock_merged_resource
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


def test_setup_tracing_missing_project_id():
    """Test that setup_tracing fails gracefully when project ID is missing."""
    with patch.dict(os.environ, {}, clear=True):
        from tracing import setup_tracing

        with pytest.raises(KeyError):
            setup_tracing("test-service")


@patch("tracing.trace.get_tracer")
def test_get_tracer(mock_get_tracer):
    """Test that get_tracer calls the OpenTelemetry get_tracer function."""
    mock_tracer = MagicMock()
    mock_get_tracer.return_value = mock_tracer

    from tracing import get_tracer

    result = get_tracer("test-service")

    mock_get_tracer.assert_called_once_with("test-service")
    assert result == mock_tracer


def test_get_tracer_returns_callable():
    """Test that get_tracer returns something that looks like a tracer."""
    from tracing import get_tracer

    tracer = get_tracer("test-service")

    # Should have tracer methods
    assert hasattr(tracer, "start_span") or hasattr(tracer, "start_as_current_span")
