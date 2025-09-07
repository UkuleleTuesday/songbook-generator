"""Tests for the tag updater cloud function."""

import base64
import json
from unittest.mock import Mock, patch

import click
import pytest
from cloudevents.http import CloudEvent

from .main import (
    _convert_to_file_objects,
    _get_services,
    _parse_cloud_event,
    tagupdater_main,
)


@pytest.fixture
def sample_changed_files():
    """Sample changed files data from drivewatcher."""
    return [
        {
            "id": "file1",
            "name": "Test Song 1.pdf",
            "folder_id": "folder1",
            "mime_type": "application/pdf",
            "parents": ["folder1"],
            "properties": {"status": "APPROVED"},
        },
        {
            "id": "file2",
            "name": "Test Song 2.pdf",
            "folder_id": "folder1",
            "mime_type": "application/pdf",
            "parents": ["folder1"],
            "properties": {},
        },
    ]


@pytest.fixture
def sample_cloud_event_data(sample_changed_files):
    """Sample CloudEvent data from drivewatcher."""
    return {
        "check_time": "2023-01-01T12:00:00",
        "changed_files": sample_changed_files,
        "file_count": len(sample_changed_files),
        "folders_checked": ["folder1"],
    }


def test_parse_cloud_event_direct_data(sample_cloud_event_data):
    """Test parsing CloudEvent with direct data payload."""
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, sample_cloud_event_data
    )

    result = _parse_cloud_event(cloud_event)

    assert result["changed_files"] == sample_cloud_event_data["changed_files"]
    assert result["check_time"] == "2023-01-01T12:00:00"
    assert result["file_count"] == 2


def test_parse_cloud_event_pubsub_format(sample_cloud_event_data):
    """Test parsing CloudEvent with Pub/Sub message format."""
    # Encode the data as it would come from Pub/Sub
    message_json = json.dumps(sample_cloud_event_data)
    encoded_data = base64.b64encode(message_json.encode("utf-8")).decode("utf-8")

    pubsub_data = {
        "message": {"data": encoded_data, "attributes": {"source": "drivewatcher"}}
    }

    cloud_event = CloudEvent(
        {
            "type": "google.cloud.pubsub.topic.v1.messagePublished",
            "source": "//pubsub.googleapis.com/projects/test/topics/drive-changes",
        },
        pubsub_data,
    )

    result = _parse_cloud_event(cloud_event)

    assert result["changed_files"] == sample_cloud_event_data["changed_files"]
    assert result["check_time"] == "2023-01-01T12:00:00"
    assert result["file_count"] == 2


def test_parse_cloud_event_empty_data():
    """Test parsing CloudEvent with no changed files."""
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, {"changed_files": []}
    )

    result = _parse_cloud_event(cloud_event)

    assert result["changed_files"] == []
    assert result["file_count"] == 0


def test_convert_to_file_objects(sample_changed_files):
    """Test converting changed files to File objects."""
    file_objects = _convert_to_file_objects(sample_changed_files)

    assert len(file_objects) == 2

    file1 = file_objects[0]
    assert file1.id == "file1"
    assert file1.name == "Test Song 1.pdf"
    assert file1.mimeType == "application/pdf"
    assert file1.parents == ["folder1"]
    assert file1.properties == {"status": "APPROVED"}

    file2 = file_objects[1]
    assert file2.id == "file2"
    assert file2.name == "Test Song 2.pdf"
    assert file2.properties == {}


def test_convert_to_file_objects_empty():
    """Test converting empty file list."""
    file_objects = _convert_to_file_objects([])
    assert file_objects == []


@patch("generator.tagupdater.main._get_services")
def test_tagupdater_main_success(mock_get_services, sample_cloud_event_data):
    """Test successful tag update processing."""
    # Mock services
    mock_tagger = Mock()
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {
        "tracer": mock_tracer,
        "drive": Mock(),
        "tagger": mock_tagger,
    }

    # Create cloud event
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, sample_cloud_event_data
    )

    # Call the function
    tagupdater_main(cloud_event)

    # Verify tagger was called for each file
    assert mock_tagger.update_tags.call_count == 2

    # Verify span attributes
    mock_span.set_attribute.assert_any_call("files_to_process", 2)
    mock_span.set_attribute.assert_any_call("files_processed", 2)
    mock_span.set_attribute.assert_any_call("files_error", 0)
    mock_span.set_attribute.assert_any_call("status", "success")


@patch("generator.tagupdater.main._get_services")
def test_tagupdater_main_no_files(mock_get_services):
    """Test processing with no changed files."""
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {
        "tracer": mock_tracer,
        "drive": Mock(),
        "tagger": Mock(),
    }

    # Create cloud event with no files
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, {"changed_files": []}
    )

    tagupdater_main(cloud_event)

    # Verify status was set correctly
    mock_span.set_attribute.assert_any_call("status", "no_files")


@patch("generator.tagupdater.main._get_services")
def test_tagupdater_main_with_errors(mock_get_services, sample_cloud_event_data):
    """Test processing with some tagging errors."""
    # Mock tagger to raise error on second file
    mock_tagger = Mock()
    mock_tagger.update_tags.side_effect = [None, RuntimeError("Tagging failed")]

    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {
        "tracer": mock_tracer,
        "drive": Mock(),
        "tagger": mock_tagger,
    }

    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, sample_cloud_event_data
    )

    # Should not raise exception
    tagupdater_main(cloud_event)

    # Verify final counts
    mock_span.set_attribute.assert_any_call("files_processed", 1)
    mock_span.set_attribute.assert_any_call("files_error", 1)
    mock_span.set_attribute.assert_any_call("status", "partial_success")


@patch("generator.tagupdater.main._get_services")
def test_tagupdater_main_parsing_error(mock_get_services):
    """Test handling of CloudEvent parsing errors."""
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

    mock_get_services.return_value = {
        "tracer": mock_tracer,
        "drive": Mock(),
        "tagger": Mock(),
    }

    # Create invalid cloud event that will cause parsing error
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"},
        {"message": {"data": "invalid-base64"}},
    )

    with pytest.raises(Exception):
        tagupdater_main(cloud_event)

    # Verify error status was set
    mock_span.set_attribute.assert_any_call("status", "error")


@patch("generator.tagupdater.main.get_credentials")
@patch("generator.tagupdater.main.build")
@patch("generator.tagupdater.main.get_settings")
@patch("generator.tagupdater.main.setup_tracing")
@patch("generator.tagupdater.main.get_tracer")
@patch("generator.tagupdater.main.default")
def test_get_services_success(
    mock_default,
    mock_get_tracer,
    mock_setup_tracing,
    mock_get_settings,
    mock_build,
    mock_get_credentials,
):
    """Test successful creation of services with correct credential config."""
    # Clear the cache before testing
    _get_services.cache_clear()

    # Mock default credentials
    mock_default.return_value = (None, "test-project")

    # Mock settings
    mock_credential_config = Mock()
    mock_credential_config.scopes = ["https://www.googleapis.com/auth/drive"]
    mock_credential_config.principal = "test@example.com"

    mock_settings = Mock()
    mock_settings.google_cloud.credentials.get.return_value = mock_credential_config
    mock_get_settings.return_value = mock_settings

    # Mock tracer
    mock_tracer = Mock()
    mock_get_tracer.return_value = mock_tracer

    # Mock credentials
    mock_creds = Mock()
    mock_get_credentials.return_value = mock_creds

    # Mock Google API services
    mock_drive_service = Mock()
    mock_docs_service = Mock()
    mock_build.side_effect = [mock_drive_service, mock_docs_service]

    # Call the function
    result = _get_services()

    # Verify credentials config lookup used correct key
    mock_settings.google_cloud.credentials.get.assert_called_once_with(
        "songbook-generator"
    )

    # Verify get_credentials was called correctly
    mock_get_credentials.assert_called_once_with(
        scopes=mock_credential_config.scopes,
        target_principal=mock_credential_config.principal,
    )

    # Verify both services were built
    assert mock_build.call_count == 2
    mock_build.assert_any_call("drive", "v3", credentials=mock_creds)
    mock_build.assert_any_call("docs", "v1", credentials=mock_creds)

    # Verify return structure
    assert "tracer" in result
    assert "drive" in result
    assert "tagger" in result
    assert result["tracer"] == mock_tracer
    assert result["drive"] == mock_drive_service

    # Verify Tagger was created with both services
    # Note: We can't easily verify the Tagger constructor call without mocking it,
    # but we can verify the tagger object exists
    assert result["tagger"] is not None


@patch("generator.tagupdater.main.get_settings")
@patch("generator.tagupdater.main.setup_tracing")
@patch("generator.tagupdater.main.get_tracer")
@patch("generator.tagupdater.main.default")
def test_get_services_missing_credential_config(
    mock_default, mock_get_tracer, mock_setup_tracing, mock_get_settings
):
    """Test error handling when credential config is not found."""
    # Clear the cache before testing
    _get_services.cache_clear()

    # Mock default credentials
    mock_default.return_value = (None, "test-project")

    # Mock settings with missing credential config
    mock_settings = Mock()
    mock_settings.google_cloud.credentials.get.return_value = None
    mock_get_settings.return_value = mock_settings

    # Mock tracer
    mock_tracer = Mock()
    mock_get_tracer.return_value = mock_tracer

    # Call the function and expect it to raise
    with pytest.raises(click.Abort):
        _get_services()

    # Verify the correct credential config was requested
    mock_settings.google_cloud.credentials.get.assert_called_once_with(
        "songbook-generator"
    )


@patch("generator.tagupdater.main.Tagger")
@patch("generator.tagupdater.main.get_credentials")
@patch("generator.tagupdater.main.build")
@patch("generator.tagupdater.main.get_settings")
@patch("generator.tagupdater.main.setup_tracing")
@patch("generator.tagupdater.main.get_tracer")
@patch("generator.tagupdater.main.default")
def test_get_services_tagger_instantiation(
    mock_default,
    mock_get_tracer,
    mock_setup_tracing,
    mock_get_settings,
    mock_build,
    mock_get_credentials,
    mock_tagger_class,
):
    """Test that Tagger is instantiated with both drive_service and docs_service."""
    # Clear the cache before testing
    _get_services.cache_clear()

    # Mock default credentials
    mock_default.return_value = (None, "test-project")

    # Mock settings
    mock_credential_config = Mock()
    mock_credential_config.scopes = ["https://www.googleapis.com/auth/drive"]
    mock_credential_config.principal = "test@example.com"

    mock_settings = Mock()
    mock_settings.google_cloud.credentials.get.return_value = mock_credential_config
    mock_get_settings.return_value = mock_settings

    # Mock tracer
    mock_tracer = Mock()
    mock_get_tracer.return_value = mock_tracer

    # Mock credentials
    mock_creds = Mock()
    mock_get_credentials.return_value = mock_creds

    # Mock Google API services
    mock_drive_service = Mock()
    mock_docs_service = Mock()
    mock_build.side_effect = [mock_drive_service, mock_docs_service]

    # Mock Tagger instance
    mock_tagger_instance = Mock()
    mock_tagger_class.return_value = mock_tagger_instance

    # Call the function
    result = _get_services()

    # Verify Tagger was instantiated with both services
    mock_tagger_class.assert_called_once_with(mock_drive_service, mock_docs_service)

    # Verify the tagger is returned
    assert result["tagger"] == mock_tagger_instance
