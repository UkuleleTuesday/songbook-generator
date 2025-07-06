"""Tests for the tracing module."""

import os
from unittest.mock import patch, MagicMock


@patch("tracing.google.auth.default")
@patch("tracing.grpc.composite_channel_credentials")
@patch("tracing.grpc.ssl_channel_credentials")
@patch("tracing.grpc.metadata_call_credentials")
@patch("tracing.AuthMetadataPlugin")
@patch("tracing.trace.set_tracer_provider")
@patch("tracing.TracerProvider")
@patch("tracing.BatchSpanProcessor")
@patch("tracing.OTLPSpanExporter")
def test_setup_tracing_runs_without_error(
    mock_exporter,
    mock_processor,
    mock_provider,
    mock_set_provider,
    mock_auth_plugin,
    mock_metadata_creds,
    mock_ssl_creds,
    mock_composite_creds,
    mock_auth_default,
):
    """Test that setup_tracing can be called without raising exceptions."""
    # Mock the return values
    mock_credentials = MagicMock()
    mock_project_id = "test-project"
    mock_auth_default.return_value = (mock_credentials, mock_project_id)

    mock_ssl_creds.return_value = MagicMock()
    mock_metadata_creds.return_value = MagicMock()
    mock_composite_creds.return_value = MagicMock()
    mock_auth_plugin.return_value = MagicMock()
    mock_exporter.return_value = MagicMock()
    mock_processor.return_value = MagicMock()
    mock_provider.return_value = MagicMock()

    from tracing import setup_tracing

    # Should not raise any exceptions
    setup_tracing()

    # Verify key functions were called
    mock_auth_default.assert_called_once()
    mock_set_provider.assert_called_once()


def test_get_tracer_with_project_id():
    """Test that get_tracer returns a tracer when project ID is available."""
    with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project"}):
        from tracing import get_tracer

        tracer = get_tracer("test-service")

        # Should return a tracer with expected methods
        assert hasattr(tracer, "start_span") or hasattr(tracer, "start_as_current_span")


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
