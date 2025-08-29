"""Tests for the drivewatcher module."""

import json
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch


from generator.drivewatcher.main import (
    _detect_changes,
    _get_last_check_time,
    _get_watched_folders,
    _publish_changes,
    _save_check_time,
    drivewatcher_main,
)
from generator.worker.models import File


def test_get_watched_folders_from_env():
    """Test getting watched folders from environment variable."""
    with patch.dict(os.environ, {"DRIVE_WATCHED_FOLDERS": "folder1,folder2,folder3"}):
        folders = _get_watched_folders()
        assert folders == ["folder1", "folder2", "folder3"]


def test_get_watched_folders_from_config(monkeypatch):
    """Test getting watched folders from config when env var not set."""
    # Clear the environment variable
    monkeypatch.delenv("DRIVE_WATCHED_FOLDERS", raising=False)

    # Mock the settings
    mock_settings = Mock()
    mock_settings.song_sheets.folder_ids = ["config_folder1", "config_folder2"]

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        folders = _get_watched_folders()
        assert folders == ["config_folder1", "config_folder2"]


def test_get_watched_folders_strips_whitespace():
    """Test that folder IDs are stripped of whitespace."""
    with patch.dict(os.environ, {"DRIVE_WATCHED_FOLDERS": " folder1 , folder2 ,  "}):
        folders = _get_watched_folders()
        assert folders == ["folder1", "folder2"]


@patch("generator.drivewatcher.main.init_cache")
@patch("generator.drivewatcher.main.GoogleDriveClient")
def test_detect_changes(mock_gdrive_client, mock_init_cache):
    """Test the change detection logic."""
    # Mock the tracer and services
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    services = {
        "tracer": mock_tracer,
        "drive": Mock(),
    }

    # Mock the Google Drive client
    mock_client_instance = Mock()
    mock_gdrive_client.return_value = mock_client_instance

    # Create mock files
    mock_files = [
        File(
            id="file1",
            name="Test File 1.pdf",
            mimeType="application/pdf",
            parents=["folder1"],
            properties={},
        ),
        File(
            id="file2",
            name="Test File 2.pdf",
            mimeType="application/pdf",
            parents=["folder1"],
            properties={},
        ),
    ]

    mock_client_instance.query_drive_files.return_value = mock_files

    # Test the function
    since_time = datetime.utcnow() - timedelta(hours=1)
    changed_files = _detect_changes(services, ["folder1"], since_time)

    # Verify the results
    assert len(changed_files) == 2
    assert changed_files[0]["id"] == "file1"
    assert changed_files[0]["name"] == "Test File 1.pdf"
    assert changed_files[1]["id"] == "file2"
    assert changed_files[1]["name"] == "Test File 2.pdf"

    # Verify the Google Drive client was called correctly
    mock_client_instance.query_drive_files.assert_called_once_with(
        "folder1", modified_after=since_time
    )


def test_get_last_check_time_no_blob():
    """Test getting last check time when no previous check exists."""
    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = None

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _get_last_check_time(services)

        # Should return approximately 1 hour ago
        now = datetime.utcnow()
        expected = now - timedelta(hours=1)
        assert (
            abs((result - expected).total_seconds()) < 60
        )  # Within 1 minute tolerance

        # Verify it looked for the correct file
        mock_bucket.get_blob.assert_called_once_with("drivewatcher/metadata.json")


def test_get_last_check_time_with_existing_blob():
    """Test getting last check time when a previous check time exists."""
    test_time = datetime(2023, 1, 1, 12, 0, 0)

    mock_blob = Mock()
    metadata = {"last_check_time": test_time.isoformat()}
    mock_blob.download_as_text.return_value = json.dumps(metadata)

    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _get_last_check_time(services)

        assert result == test_time
        mock_bucket.get_blob.assert_called_once_with("drivewatcher/metadata.json")


def test_get_last_check_time_malformed_json():
    """Test getting last check time when JSON metadata is malformed."""
    mock_blob = Mock()
    mock_blob.download_as_text.return_value = "invalid json"

    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _get_last_check_time(services)

        # Should fallback to 1 hour ago when JSON is malformed
        now = datetime.utcnow()
        expected = now - timedelta(hours=1)
        assert (
            abs((result - expected).total_seconds()) < 60
        )  # Within 1 minute tolerance


def test_save_check_time():
    """Test saving the check time."""
    test_time = datetime(2023, 1, 1, 12, 0, 0)

    mock_blob = Mock()
    mock_bucket = Mock()
    mock_bucket.blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        _save_check_time(services, test_time)

        # Verify the blob was created and uploaded correctly
        mock_bucket.blob.assert_called_once_with("drivewatcher/metadata.json")

        # Check that JSON was uploaded with correct structure
        call_args = mock_blob.upload_from_string.call_args
        uploaded_data = call_args[0][0]
        uploaded_metadata = json.loads(uploaded_data)

        assert uploaded_metadata["last_check_time"] == test_time.isoformat()
        assert call_args[1]["content_type"] == "application/json"


def test_publish_changes():
    """Test publishing changes to Pub/Sub."""
    check_time = datetime(2023, 1, 1, 12, 0, 0)
    changed_files = [
        {"id": "file1", "name": "Test File 1.pdf", "folder_id": "folder1"},
        {"id": "file2", "name": "Test File 2.pdf", "folder_id": "folder1"},
    ]

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

    services = {
        "tracer": mock_tracer,
        "publisher": mock_publisher,
        "topic_path": "projects/test-project/topics/test-topic",
    }

    with patch(
        "generator.drivewatcher.main._get_watched_folders", return_value=["folder1"]
    ):
        _publish_changes(services, changed_files, check_time)

    # Verify the message was published
    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args

    assert call_args[0][0] == "projects/test-project/topics/test-topic"  # topic path

    # Parse the message data
    message_data = json.loads(call_args[0][1].decode("utf-8"))
    assert message_data["check_time"] == check_time.isoformat()
    assert message_data["file_count"] == 2
    assert message_data["changed_files"] == changed_files
    assert message_data["folders_checked"] == ["folder1"]

    # Check the attributes
    assert call_args[1]["source"] == "drivewatcher"
    assert call_args[1]["change_count"] == "2"


def test_publish_changes_empty_list():
    """Test that nothing is published when there are no changes."""
    services = {"tracer": Mock(), "publisher": Mock()}

    _publish_changes(services, [], datetime.utcnow())

    # Verify no publish call was made
    services["publisher"].publish.assert_not_called()


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
@patch("generator.drivewatcher.main._get_last_check_time")
@patch("generator.drivewatcher.main._detect_changes")
@patch("generator.drivewatcher.main._publish_changes")
@patch("generator.drivewatcher.main._save_check_time")
def test_drivewatcher_main_with_changes(
    mock_save_check_time,
    mock_publish_changes,
    mock_detect_changes,
    mock_get_last_check_time,
    mock_get_watched_folders,
    mock_get_services,
):
    """Test the main drivewatcher function when changes are detected."""
    # Mock the services
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {"tracer": mock_tracer}

    # Mock the watched folders
    mock_get_watched_folders.return_value = ["folder1", "folder2"]

    # Mock the last check time
    last_check_time = datetime.utcnow() - timedelta(hours=1)
    mock_get_last_check_time.return_value = last_check_time

    # Mock detecting changes
    changed_files = [{"id": "file1", "name": "Test File.pdf"}]
    mock_detect_changes.return_value = changed_files

    # Mock cloud event
    cloud_event = Mock()

    # Call the function
    drivewatcher_main(cloud_event)

    # Verify all functions were called
    mock_get_watched_folders.assert_called_once()
    mock_get_last_check_time.assert_called_once()
    mock_detect_changes.assert_called_once_with(
        mock_get_services.return_value, ["folder1", "folder2"], last_check_time
    )
    mock_publish_changes.assert_called_once()
    mock_save_check_time.assert_called_once()


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
def test_drivewatcher_main_no_folders(mock_get_watched_folders, mock_get_services):
    """Test the main drivewatcher function when no folders are configured."""
    # Mock the services
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {"tracer": mock_tracer}

    # Mock no watched folders
    mock_get_watched_folders.return_value = []

    # Mock cloud event
    cloud_event = Mock()

    # Call the function
    drivewatcher_main(cloud_event)

    # Verify status was set to failed
    mock_span.set_attribute.assert_any_call("status", "failed_no_folders")
