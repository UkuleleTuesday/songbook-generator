"""Tests for the drivewatcher watch module."""

import json
import os
from unittest.mock import Mock, patch

import pytest
from google.api_core.exceptions import GoogleAPICallError, NotFound

from generator.drivewatcher.watch import (
    create_watch_channel,
    get_channel_metadata,
    get_page_token,
    get_start_page_token,
    initialize_watch,
    renew_watch,
    save_channel_metadata,
    save_page_token,
    stop_watch_channel,
    drivewatch_main,
)


def _make_storage_services(blob_data=None, blob_missing=False):
    """Helper to build a mock services dict with storage."""
    mock_blob = Mock()
    if blob_missing:
        mock_blob = None
    elif blob_data is not None:
        mock_blob_obj = Mock()
        mock_blob_obj.download_as_text.return_value = json.dumps(blob_data)
        mock_blob = mock_blob_obj

    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = mock_blob

    mock_upload_blob = Mock()
    mock_bucket.blob.return_value = mock_upload_blob

    mock_storage = Mock()
    mock_storage.bucket.return_value = mock_bucket

    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    return {
        "tracer": mock_tracer,
        "drive": Mock(),
        "storage_client": mock_storage,
        "project_id": "test-project",
    }, mock_upload_blob


def test_get_channel_metadata_present():
    """Test reading channel metadata when a blob exists."""
    data = {
        "channel_id": "ch-1",
        "resource_id": "res-1",
        "expiration": "9999999",
    }
    services, _ = _make_storage_services(blob_data=data)

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"
    with patch(
        "generator.drivewatcher.watch.get_settings",
        return_value=mock_settings,
    ):
        result = get_channel_metadata(services)

    assert result == data


def test_get_channel_metadata_missing():
    """Test that None is returned when no metadata blob exists."""
    services, _ = _make_storage_services(blob_missing=True)

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"
    with patch(
        "generator.drivewatcher.watch.get_settings",
        return_value=mock_settings,
    ):
        result = get_channel_metadata(services)

    assert result is None


def test_save_channel_metadata():
    """Test that channel metadata is written to GCS correctly."""
    services, upload_blob = _make_storage_services()

    data = {"channel_id": "ch-1", "resource_id": "res-1"}
    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"
    with patch(
        "generator.drivewatcher.watch.get_settings",
        return_value=mock_settings,
    ):
        save_channel_metadata(services, data)

    upload_blob.upload_from_string.assert_called_once()
    call_args = upload_blob.upload_from_string.call_args
    saved = json.loads(call_args[0][0])
    assert saved == data
    assert call_args[1]["content_type"] == "application/json"


def test_get_page_token_present():
    """Test reading page token when a blob exists."""
    services, _ = _make_storage_services(blob_data={"page_token": "tok-123"})

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"
    with patch(
        "generator.drivewatcher.watch.get_settings",
        return_value=mock_settings,
    ):
        result = get_page_token(services)

    assert result == "tok-123"


def test_get_page_token_missing():
    """Test that None is returned when no page token blob exists."""
    services, _ = _make_storage_services(blob_missing=True)

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"
    with patch(
        "generator.drivewatcher.watch.get_settings",
        return_value=mock_settings,
    ):
        result = get_page_token(services)

    assert result is None


def test_save_page_token():
    """Test that page token is persisted to GCS with timestamp."""
    services, upload_blob = _make_storage_services()

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"
    with patch(
        "generator.drivewatcher.watch.get_settings",
        return_value=mock_settings,
    ):
        save_page_token(services, "tok-999")

    call_args = upload_blob.upload_from_string.call_args
    saved = json.loads(call_args[0][0])
    assert saved["page_token"] == "tok-999"
    assert "updated_at" in saved


def test_get_start_page_token():
    """Test fetching a fresh start page token from the Drive API."""
    services, _ = _make_storage_services()
    services[
        "drive"
    ].changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "start-tok"
    }

    result = get_start_page_token(services)

    assert result == "start-tok"
    services["drive"].changes.return_value.getStartPageToken.assert_called_once_with(
        supportsAllDrives=True
    )


def test_create_watch_channel():
    """Test creating a new watch channel."""
    services, _ = _make_storage_services()
    services["drive"].changes.return_value.watch.return_value.execute.return_value = {
        "id": "ch-new",
        "resourceId": "res-new",
        "expiration": "9999999",
    }

    result = create_watch_channel(
        services, "tok-1", "https://example.com/hook", "verify-token"
    )

    assert result["channel_id"] == "ch-new"
    assert result["resource_id"] == "res-new"
    assert result["expiration"] == "9999999"
    assert "created_at" in result

    watch_call = services["drive"].changes.return_value.watch
    watch_call.assert_called_once()
    call_kwargs = watch_call.call_args[1]
    assert call_kwargs["pageToken"] == "tok-1"
    assert call_kwargs["supportsAllDrives"] is True
    assert call_kwargs["includeItemsFromAllDrives"] is True
    body = call_kwargs["body"]
    assert body["type"] == "web_hook"
    assert body["address"] == "https://example.com/hook"
    assert body["token"] == "verify-token"
    assert "id" in body
    assert "expiration" in body


def test_stop_watch_channel_success():
    """Test stopping a watch channel successfully."""
    services, _ = _make_storage_services()
    services["drive"].channels.return_value.stop.return_value.execute.return_value = {}

    stop_watch_channel(services, "ch-1", "res-1")

    services["drive"].channels.return_value.stop.assert_called_once_with(
        body={"id": "ch-1", "resourceId": "res-1"}
    )


def test_stop_watch_channel_not_found():
    """Test that NotFound during stop is handled gracefully."""
    services, _ = _make_storage_services()
    services[
        "drive"
    ].channels.return_value.stop.return_value.execute.side_effect = NotFound(
        "channel not found"
    )

    # Should not raise
    stop_watch_channel(services, "ch-1", "res-1")


def test_stop_watch_channel_api_error():
    """Test that API errors during stop are handled gracefully."""
    services, _ = _make_storage_services()
    services[
        "drive"
    ].channels.return_value.stop.return_value.execute.side_effect = GoogleAPICallError(
        "server error"
    )

    # Should not raise
    stop_watch_channel(services, "ch-1", "res-1")


@patch("generator.drivewatcher.watch.get_settings")
@patch("generator.drivewatcher.watch.get_start_page_token")
@patch("generator.drivewatcher.watch.save_page_token")
@patch("generator.drivewatcher.watch.create_watch_channel")
@patch("generator.drivewatcher.watch.save_channel_metadata")
def test_initialize_watch(
    mock_save_meta,
    mock_create_channel,
    mock_save_token,
    mock_get_start_token,
    mock_get_settings,
):
    """Test full watch initialization flow."""
    mock_get_start_token.return_value = "start-tok"
    mock_create_channel.return_value = {
        "channel_id": "ch-1",
        "resource_id": "res-1",
        "expiration": "9999999",
        "created_at": "2024-01-01T00:00:00",
    }

    services, _ = _make_storage_services()

    result = initialize_watch(services, "https://example.com/hook", "tok")

    mock_get_start_token.assert_called_once_with(services)
    mock_save_token.assert_called_once_with(services, "start-tok")
    mock_create_channel.assert_called_once_with(
        services, "start-tok", "https://example.com/hook", "tok"
    )
    mock_save_meta.assert_called_once()
    saved_meta = mock_save_meta.call_args[0][1]
    assert saved_meta["page_token"] == "start-tok"
    assert result["channel_id"] == "ch-1"


@patch("generator.drivewatcher.watch.get_settings")
@patch("generator.drivewatcher.watch.get_channel_metadata")
@patch("generator.drivewatcher.watch.get_page_token")
@patch("generator.drivewatcher.watch.create_watch_channel")
@patch("generator.drivewatcher.watch.save_channel_metadata")
@patch("generator.drivewatcher.watch.stop_watch_channel")
def test_renew_watch_with_existing_channel(
    mock_stop,
    mock_save_meta,
    mock_create_channel,
    mock_get_token,
    mock_get_meta,
    mock_get_settings,
):
    """Test watch renewal when an existing channel is present."""
    mock_get_meta.return_value = {
        "channel_id": "old-ch",
        "resource_id": "old-res",
    }
    mock_get_token.return_value = "current-tok"
    mock_create_channel.return_value = {
        "channel_id": "new-ch",
        "resource_id": "new-res",
        "expiration": "9999999",
        "created_at": "2024-01-01T00:00:00",
    }

    services, _ = _make_storage_services()

    result = renew_watch(services, "https://example.com/hook", "tok")

    mock_create_channel.assert_called_once_with(
        services, "current-tok", "https://example.com/hook", "tok"
    )
    mock_save_meta.assert_called_once()
    mock_stop.assert_called_once_with(services, "old-ch", "old-res")
    assert result["channel_id"] == "new-ch"


@patch("generator.drivewatcher.watch.get_settings")
@patch("generator.drivewatcher.watch.get_channel_metadata")
@patch("generator.drivewatcher.watch.get_page_token")
@patch("generator.drivewatcher.watch.get_start_page_token")
@patch("generator.drivewatcher.watch.save_page_token")
@patch("generator.drivewatcher.watch.create_watch_channel")
@patch("generator.drivewatcher.watch.save_channel_metadata")
@patch("generator.drivewatcher.watch.stop_watch_channel")
def test_renew_watch_no_page_token(
    mock_stop,
    mock_save_meta,
    mock_create_channel,
    mock_save_token,
    mock_get_start_token,
    mock_get_token,
    mock_get_meta,
    mock_get_settings,
):
    """Test that renewal fetches a start token when none is stored."""
    mock_get_meta.return_value = {
        "channel_id": "old-ch",
        "resource_id": "old-res",
    }
    mock_get_token.return_value = None
    mock_get_start_token.return_value = "fresh-tok"
    mock_create_channel.return_value = {
        "channel_id": "new-ch",
        "resource_id": "new-res",
        "expiration": "9999999",
        "created_at": "2024-01-01T00:00:00",
    }

    services, _ = _make_storage_services()

    renew_watch(services, "https://example.com/hook", "tok")

    mock_get_start_token.assert_called_once_with(services)
    mock_save_token.assert_called_once_with(services, "fresh-tok")
    mock_create_channel.assert_called_once_with(
        services, "fresh-tok", "https://example.com/hook", "tok"
    )


@patch("generator.drivewatcher.watch._get_services")
@patch("generator.drivewatcher.watch.get_channel_metadata")
@patch("generator.drivewatcher.watch.initialize_watch")
def test_drivewatch_main_initializes_when_no_channel(
    mock_init, mock_get_meta, mock_get_services
):
    """Test that drivewatch_main initializes a new channel when none exists."""
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_meta.return_value = None
    mock_init.return_value = {
        "channel_id": "new-ch",
        "resource_id": "new-res",
        "expiration": "9999999",
    }

    cloud_event = Mock()
    with patch.dict(
        os.environ,
        {
            "DRIVE_WEBHOOK_URL": "https://example.com/hook",
            "VERIFY_TOKEN": "tok",
        },
    ):
        drivewatch_main(cloud_event)

    mock_init.assert_called_once_with(
        mock_get_services.return_value,
        "https://example.com/hook",
        "tok",
    )


@patch("generator.drivewatcher.watch._get_services")
@patch("generator.drivewatcher.watch.get_channel_metadata")
@patch("generator.drivewatcher.watch.renew_watch")
def test_drivewatch_main_renews_existing_channel(
    mock_renew, mock_get_meta, mock_get_services
):
    """Test that drivewatch_main renews when a channel already exists."""
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_meta.return_value = {
        "channel_id": "old-ch",
        "resource_id": "old-res",
    }
    mock_renew.return_value = {
        "channel_id": "new-ch",
        "resource_id": "new-res",
        "expiration": "9999999",
    }

    cloud_event = Mock()
    with patch.dict(
        os.environ,
        {
            "DRIVE_WEBHOOK_URL": "https://example.com/hook",
            "VERIFY_TOKEN": "tok",
        },
    ):
        drivewatch_main(cloud_event)

    mock_renew.assert_called_once_with(
        mock_get_services.return_value,
        "https://example.com/hook",
        "tok",
    )


@patch("generator.drivewatcher.watch._get_services")
def test_drivewatch_main_fails_without_webhook_url(mock_get_services):
    """Test that drivewatch_main raises when DRIVE_WEBHOOK_URL is missing."""
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)
    mock_get_services.return_value = {"tracer": mock_tracer}

    env = {"VERIFY_TOKEN": "tok"}
    env.pop("DRIVE_WEBHOOK_URL", None)

    cloud_event = Mock()
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DRIVE_WEBHOOK_URL", None)
        with pytest.raises(RuntimeError, match="DRIVE_WEBHOOK_URL"):
            drivewatch_main(cloud_event)
