from unittest.mock import Mock
import base64
import json
import pytest
from cloudevents.http import CloudEvent

from generator.cache_updater.main import _parse_cloud_event


@pytest.fixture
def mock_cloud_event():
    """Fixture to create a mock CloudEvent."""

    def _create_event(attributes=None, data=None):
        if data is None:
            data = {"message": {"attributes": attributes or {}}}
        event = Mock(spec=CloudEvent)
        event.get_attributes.return_value = {}  # Mock top-level attributes
        event.get_data.return_value = data
        return event

    return _create_event


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
def sample_drive_change_data(sample_changed_files):
    """Sample CloudEvent data from drivewatcher."""
    return {
        "check_time": "2023-01-01T12:00:00",
        "changed_files": sample_changed_files,
        "file_count": len(sample_changed_files),
        "folders_checked": ["folder1"],
    }


# Legacy force sync tests
def test_parse_cloud_event_force_sync_true(mock_cloud_event):
    """Test parsing with 'force' attribute set to 'true'."""
    event = mock_cloud_event(attributes={"force": "true"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is True
    assert result["changed_files"] == []
    assert result["check_time"] is None
    assert result["file_count"] == 0


def test_parse_cloud_event_force_sync_false(mock_cloud_event):
    """Test parsing with 'force' attribute set to 'false'."""
    event = mock_cloud_event(attributes={"force": "false"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False
    assert result["changed_files"] == []


def test_parse_cloud_event_force_sync_case_insensitive(mock_cloud_event):
    """Test that 'force' attribute parsing is case-insensitive."""
    event = mock_cloud_event(attributes={"force": "True"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is True


def test_parse_cloud_event_no_force_attribute(mock_cloud_event):
    """Test parsing when 'force' attribute is missing."""
    event = mock_cloud_event(attributes={})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


def test_parse_cloud_event_no_attributes(mock_cloud_event):
    """Test parsing when the message has no 'attributes' key."""
    event = mock_cloud_event(attributes=None)
    event.get_data.return_value = {"message": {}}
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


def test_parse_cloud_event_no_message(mock_cloud_event):
    """Test parsing when the data has no 'message' key."""
    event = mock_cloud_event(data={})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


def test_parse_cloud_event_no_data(mock_cloud_event):
    """Test parsing when the CloudEvent has no data payload."""
    event = mock_cloud_event(data=None)
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


# Drive change event tests
def test_parse_cloud_event_direct_drive_data(sample_drive_change_data):
    """Test parsing CloudEvent with direct drive change data payload."""
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, sample_drive_change_data
    )

    result = _parse_cloud_event(cloud_event)

    assert result["force_sync"] is False
    assert result["changed_files"] == sample_drive_change_data["changed_files"]
    assert result["check_time"] == "2023-01-01T12:00:00"
    assert result["file_count"] == 2


def test_parse_cloud_event_pubsub_drive_format(sample_drive_change_data):
    """Test parsing CloudEvent with Pub/Sub message format from drivewatcher."""
    # Encode the data as it would come from Pub/Sub
    message_json = json.dumps(sample_drive_change_data)
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

    assert result["force_sync"] is False
    assert result["changed_files"] == sample_drive_change_data["changed_files"]
    assert result["check_time"] == "2023-01-01T12:00:00"
    assert result["file_count"] == 2


def test_parse_cloud_event_empty_drive_changes():
    """Test parsing CloudEvent with no changed files."""
    cloud_event = CloudEvent(
        {"type": "test.event", "source": "test"}, {"changed_files": []}
    )

    result = _parse_cloud_event(cloud_event)

    assert result["force_sync"] is False
    assert result["changed_files"] == []
    assert result["file_count"] == 0


def test_parse_cloud_event_combined_force_and_changes(sample_drive_change_data):
    """Test parsing CloudEvent with both force attribute and drive changes."""
    # This could happen if someone manually triggers with force while changes exist
    message_json = json.dumps(sample_drive_change_data)
    encoded_data = base64.b64encode(message_json.encode("utf-8")).decode("utf-8")

    pubsub_data = {"message": {"data": encoded_data, "attributes": {"force": "true"}}}

    cloud_event = CloudEvent(
        {"type": "google.cloud.pubsub.topic.v1.messagePublished", "source": "test"},
        pubsub_data,
    )

    result = _parse_cloud_event(cloud_event)

    # Force sync should take precedence
    assert result["force_sync"] is True
    assert result["changed_files"] == sample_drive_change_data["changed_files"]
    assert result["check_time"] == "2023-01-01T12:00:00"
    assert result["file_count"] == 2


def test_parse_cloud_event_invalid_base64():
    """Test parsing CloudEvent with invalid base64 data."""
    pubsub_data = {"message": {"data": "invalid-base64-data", "attributes": {}}}

    cloud_event = CloudEvent(
        {"type": "google.cloud.pubsub.topic.v1.messagePublished", "source": "test"},
        pubsub_data,
    )

    result = _parse_cloud_event(cloud_event)

    # Should fall back to force sync logic
    assert result["force_sync"] is False
    assert result["changed_files"] == []
    assert result["file_count"] == 0
