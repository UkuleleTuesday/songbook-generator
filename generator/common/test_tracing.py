"""Tests for the tracing module."""

import pytest
import os
from unittest.mock import patch

import google.auth
import google.auth.transport.grpc
import google.auth.transport.requests


# 1) A minimal fake credentials class
class DummyCreds(google.auth.credentials.Credentials):
    def __init__(self):
        super().__init__()
        self.token = "fake-token"

    # Called by AuthMetadataPlugin under the hood; we just stash a header
    def before_request(self, request, method, url, headers):
        headers["authorization"] = f"Bearer {self.token}"

    # No network call here!
    def refresh(self, request):
        self.token = "refreshed-token"


@pytest.fixture(autouse=True)
def stub_adc(monkeypatch):
    # Make google.auth.default() return our dummy creds and a dummy project
    monkeypatch.setattr(google.auth, "default", lambda: (DummyCreds(), "test-project"))
    yield


def test_setup_tracing_runs_without_error(monkeypatch):
    """Test that setup_tracing can be called without raising exceptions."""

    from tracing import setup_tracing

    # Should not raise any exceptions
    setup_tracing("test-service")


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
