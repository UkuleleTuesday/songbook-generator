"""Tests for the drivewebhook module."""

import json
import os
from unittest.mock import Mock, patch

from generator.drivewebhook.main import _validate_token, drivewebhook_main


def test_validate_token_matches():
    """Test that matching tokens are accepted."""
    assert _validate_token("secret-token", "secret-token") is True


def test_validate_token_mismatch():
    """Test that mismatched tokens are rejected."""
    assert _validate_token("wrong-token", "secret-token") is False


def test_validate_token_empty():
    """Test that empty token is rejected when verify token is set."""
    assert _validate_token("", "secret-token") is False


def test_validate_token_both_empty():
    """Test that two empty tokens compare equal (constant-time)."""
    assert _validate_token("", "") is True


@patch("generator.drivewebhook.main._get_services")
def test_drivewebhook_main_valid_token(mock_get_services):
    """Test successful webhook notification with valid token."""
    mock_future = Mock()
    mock_future.result.return_value = None

    mock_publisher = Mock()
    mock_publisher.publish.return_value = mock_future

    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {
        "tracer": mock_tracer,
        "publisher": mock_publisher,
        "topic_path": "projects/test/topics/drive-webhook",
    }

    mock_request = Mock()
    mock_request.headers = {
        "X-Goog-Channel-Token": "my-secret",
        "X-Goog-Channel-Id": "channel-123",
        "X-Goog-Resource-Id": "resource-456",
        "X-Goog-Resource-State": "change",
        "X-Goog-Message-Number": "1",
    }

    with patch.dict(os.environ, {"VERIFY_TOKEN": "my-secret"}):
        response, status_code = drivewebhook_main(mock_request)

    assert status_code == 204
    mock_publisher.publish.assert_called_once()

    call_args = mock_publisher.publish.call_args
    assert call_args[0][0] == "projects/test/topics/drive-webhook"
    payload = json.loads(call_args[0][1].decode("utf-8"))
    assert payload["channel_id"] == "channel-123"
    assert payload["resource_id"] == "resource-456"
    assert payload["resource_state"] == "change"
    assert payload["message_number"] == "1"
    assert call_args[1]["resource_state"] == "change"


@patch("generator.drivewebhook.main._get_services")
def test_drivewebhook_main_invalid_token(mock_get_services):
    """Test that invalid token returns 403."""
    mock_get_services.return_value = {
        "tracer": Mock(),
        "publisher": Mock(),
        "topic_path": "projects/test/topics/drive-webhook",
    }

    mock_request = Mock()
    mock_request.headers = {
        "X-Goog-Channel-Token": "wrong-token",
        "X-Goog-Resource-State": "change",
    }

    with patch.dict(os.environ, {"VERIFY_TOKEN": "my-secret"}):
        response, status_code = drivewebhook_main(mock_request)

    assert status_code == 403
    mock_get_services.return_value["publisher"].publish.assert_not_called()


@patch("generator.drivewebhook.main._get_services")
def test_drivewebhook_main_missing_token(mock_get_services):
    """Test that missing token returns 403."""
    mock_get_services.return_value = {
        "tracer": Mock(),
        "publisher": Mock(),
        "topic_path": "projects/test/topics/drive-webhook",
    }

    mock_request = Mock()
    mock_request.headers = {
        "X-Goog-Resource-State": "change",
    }

    with patch.dict(os.environ, {"VERIFY_TOKEN": "my-secret"}):
        response, status_code = drivewebhook_main(mock_request)

    assert status_code == 403


@patch("generator.drivewebhook.main._get_services")
def test_drivewebhook_main_publish_error(mock_get_services):
    """Test that Pub/Sub publish failure returns 500."""
    from google.api_core.exceptions import GoogleAPICallError

    mock_future = Mock()
    mock_future.result.side_effect = GoogleAPICallError("publish failed")

    mock_publisher = Mock()
    mock_publisher.publish.return_value = mock_future

    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {
        "tracer": mock_tracer,
        "publisher": mock_publisher,
        "topic_path": "projects/test/topics/drive-webhook",
    }

    mock_request = Mock()
    mock_request.headers = {
        "X-Goog-Channel-Token": "my-secret",
        "X-Goog-Channel-Id": "channel-123",
        "X-Goog-Resource-Id": "resource-456",
        "X-Goog-Resource-State": "change",
        "X-Goog-Message-Number": "1",
    }

    with patch.dict(os.environ, {"VERIFY_TOKEN": "my-secret"}):
        response, status_code = drivewebhook_main(mock_request)

    assert status_code == 500
