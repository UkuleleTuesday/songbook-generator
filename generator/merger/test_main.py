from unittest.mock import Mock
import pytest
from cloudevents.http import CloudEvent

from generator.merger.main import _parse_cloud_event


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


def test_parse_cloud_event_force_sync_true(mock_cloud_event):
    """Test parsing with 'force' attribute set to 'true'."""
    event = mock_cloud_event(attributes={"force": "true"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is True


def test_parse_cloud_event_force_sync_false(mock_cloud_event):
    """Test parsing with 'force' attribute set to 'false'."""
    event = mock_cloud_event(attributes={"force": "false"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


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
