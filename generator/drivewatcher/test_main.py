"""Tests for the drivewatcher module."""

import json
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from google.api_core.exceptions import NotFound

from generator.drivewatcher.main import (
    _detect_changes,
    _filter_parent_changes,
    _get_last_check_time,
    _get_watched_folders,
    _load_file_parents,
    _publish_changes,
    _save_check_time,
    _save_file_parents,
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
        ["folder1"], modified_after=since_time
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


def test_get_last_check_time_not_found_exception():
    """Test getting last check time when blob download raises NotFound."""
    mock_blob = Mock()
    mock_blob.download_as_text.side_effect = NotFound("No such object")

    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _get_last_check_time(services)

        # Should fallback to 1 hour ago when NotFound is raised
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


def test_load_file_parents_no_blob():
    """Test loading file parents when no previous data exists."""
    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = None

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _load_file_parents(services)

    assert result == {}
    mock_bucket.get_blob.assert_called_once_with("drivewatcher/file_parents.json")


def test_load_file_parents_with_existing_data():
    """Test loading file parents when previous data exists."""
    existing_data = {
        "file1": ["folder1"],
        "file2": ["folder1", "folder2"],
    }

    mock_blob = Mock()
    mock_blob.download_as_text.return_value = json.dumps(existing_data)

    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _load_file_parents(services)

    assert result == existing_data
    mock_bucket.get_blob.assert_called_once_with("drivewatcher/file_parents.json")


def test_load_file_parents_malformed_json():
    """Test that malformed JSON returns an empty dict."""
    mock_blob = Mock()
    mock_blob.download_as_text.return_value = "not valid json"

    mock_bucket = Mock()
    mock_bucket.get_blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        result = _load_file_parents(services)

    assert result == {}


def test_save_file_parents():
    """Test saving file parents to GCS."""
    file_parents = {
        "file1": ["folder1"],
        "file2": ["folder2"],
    }

    mock_blob = Mock()
    mock_bucket = Mock()
    mock_bucket.blob.return_value = mock_blob

    mock_storage_client = Mock()
    mock_storage_client.bucket.return_value = mock_bucket

    mock_settings = Mock()
    mock_settings.caching.gcs.worker_cache_bucket = "test-bucket"

    services = {"storage_client": mock_storage_client}

    with patch("generator.drivewatcher.main.get_settings", return_value=mock_settings):
        _save_file_parents(services, file_parents)

    mock_bucket.blob.assert_called_once_with("drivewatcher/file_parents.json")
    call_args = mock_blob.upload_from_string.call_args
    saved_data = json.loads(call_args[0][0])
    assert saved_data == file_parents
    assert call_args[1]["content_type"] == "application/json"


def test_filter_parent_changes_new_file():
    """New file (never seen before) should be included."""
    changed_files = [
        {"id": "file1", "name": "New Song.pdf", "parents": ["folder1"]},
    ]
    stored_parents = {}

    filtered, updated = _filter_parent_changes(changed_files, stored_parents)

    assert len(filtered) == 1
    assert filtered[0]["id"] == "file1"
    assert updated == {"file1": ["folder1"]}


def test_filter_parent_changes_parents_changed():
    """File whose parents differ from stored state should be included."""
    changed_files = [
        {
            "id": "file1",
            "name": "Moved Song.pdf",
            "parents": ["folder2"],
        },
    ]
    stored_parents = {"file1": ["folder1"]}

    filtered, updated = _filter_parent_changes(changed_files, stored_parents)

    assert len(filtered) == 1
    assert filtered[0]["id"] == "file1"
    assert updated == {"file1": ["folder2"]}


def test_filter_parent_changes_parents_same():
    """File whose parents are unchanged should be skipped."""
    changed_files = [
        {
            "id": "file1",
            "name": "Unchanged Song.pdf",
            "parents": ["folder1"],
        },
    ]
    stored_parents = {"file1": ["folder1"]}

    filtered, updated = _filter_parent_changes(changed_files, stored_parents)

    assert filtered == []
    # Parents are still stored (unchanged)
    assert updated == {"file1": ["folder1"]}


def test_filter_parent_changes_mixed():
    """Only files with changed parents are forwarded."""
    changed_files = [
        {"id": "file1", "name": "Moved.pdf", "parents": ["folder2"]},
        {"id": "file2", "name": "Content Only.pdf", "parents": ["folder1"]},
        {"id": "file3", "name": "Brand New.pdf", "parents": ["folder1"]},
    ]
    stored_parents = {
        "file1": ["folder1"],  # was in folder1, now folder2 → changed
        "file2": ["folder1"],  # still in folder1 → no change
        # file3 not stored → new
    }

    filtered, updated = _filter_parent_changes(changed_files, stored_parents)

    filtered_ids = [f["id"] for f in filtered]
    assert "file1" in filtered_ids
    assert "file3" in filtered_ids
    assert "file2" not in filtered_ids

    assert updated == {
        "file1": ["folder2"],
        "file2": ["folder1"],
        "file3": ["folder1"],
    }


def test_filter_parent_changes_updated_includes_all_seen():
    """updated_parents must include all files, even those not forwarded."""
    changed_files = [
        {"id": "file1", "name": "Same.pdf", "parents": ["folder1"]},
    ]
    stored_parents = {"file1": ["folder1"], "file_old": ["folder1"]}

    _, updated = _filter_parent_changes(changed_files, stored_parents)

    # file_old is preserved from stored, file1 is refreshed
    assert updated["file_old"] == ["folder1"]
    assert updated["file1"] == ["folder1"]


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
@patch("generator.drivewatcher.main._get_last_check_time")
@patch("generator.drivewatcher.main._detect_changes")
@patch("generator.drivewatcher.main._publish_changes")
@patch("generator.drivewatcher.main._save_check_time")
@patch("generator.drivewatcher.main._load_file_parents")
@patch("generator.drivewatcher.main._save_file_parents")
@patch("generator.drivewatcher.main._filter_parent_changes")
def test_drivewatcher_main_with_changes(
    mock_filter_parent_changes,
    mock_save_file_parents,
    mock_load_file_parents,
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
    changed_files = [{"id": "file1", "name": "Test File.pdf", "parents": ["folder1"]}]
    mock_detect_changes.return_value = changed_files

    # Mock parent change filtering – one file with a changed parent
    stored_parents = {}
    mock_load_file_parents.return_value = stored_parents
    mock_filter_parent_changes.return_value = (changed_files, {"file1": ["folder1"]})

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
    mock_load_file_parents.assert_called_once()
    mock_filter_parent_changes.assert_called_once_with(changed_files, stored_parents)
    # updated_parents is the second element returned by the filter mock
    updated_parents = mock_filter_parent_changes.return_value[1]
    mock_save_file_parents.assert_called_once_with(
        mock_get_services.return_value, updated_parents
    )
    mock_publish_changes.assert_called_once()
    mock_save_check_time.assert_called_once()


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
@patch("generator.drivewatcher.main._get_last_check_time")
@patch("generator.drivewatcher.main._detect_changes")
@patch("generator.drivewatcher.main._publish_changes")
@patch("generator.drivewatcher.main._save_check_time")
@patch("generator.drivewatcher.main._load_file_parents")
@patch("generator.drivewatcher.main._save_file_parents")
@patch("generator.drivewatcher.main._filter_parent_changes")
def test_drivewatcher_main_no_parent_changes(
    mock_filter_parent_changes,
    mock_save_file_parents,
    mock_load_file_parents,
    mock_save_check_time,
    mock_publish_changes,
    mock_detect_changes,
    mock_get_last_check_time,
    mock_get_watched_folders,
    mock_get_services,
):
    """Test the main drivewatcher function when files changed but parents did not."""
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_watched_folders.return_value = ["folder1"]
    mock_get_last_check_time.return_value = datetime.utcnow() - timedelta(hours=1)

    changed_files = [{"id": "file1", "name": "Test File.pdf", "parents": ["folder1"]}]
    mock_detect_changes.return_value = changed_files

    stored_parents = {"file1": ["folder1"]}
    mock_load_file_parents.return_value = stored_parents
    # Filter returns no parent changes
    mock_filter_parent_changes.return_value = ([], stored_parents)

    drivewatcher_main(Mock())

    # Parents were loaded, filtered, and saved …
    mock_load_file_parents.assert_called_once()
    mock_filter_parent_changes.assert_called_once_with(changed_files, stored_parents)
    updated_parents = mock_filter_parent_changes.return_value[1]
    mock_save_file_parents.assert_called_once_with(
        mock_get_services.return_value, updated_parents
    )
    # … but nothing was published
    mock_publish_changes.assert_not_called()
    mock_span.set_attribute.assert_any_call("status", "no_parent_changes")
    # The check time should still be saved for the next run
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
