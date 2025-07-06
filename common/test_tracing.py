"""Tests for the tracing module."""

import os
from unittest.mock import patch


def test_setup_tracing_runs_without_error():
    """Test that setup_tracing can be called without raising exceptions."""
    from tracing import setup_tracing
    
    # Should not raise any exceptions
    setup_tracing()


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
