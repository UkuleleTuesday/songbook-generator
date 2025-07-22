from unittest.mock import Mock

import pytest

from .tags import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    Tagger,
    status,
    tag,
)


@pytest.fixture
def mock_drive_service():
    """Create a mock Google Drive service object."""
    return Mock()


def test_status_tagger():
    """Test the status tag function logic."""
    file_approved = {"parents": [FOLDER_ID_APPROVED]}
    assert status(file_approved) == "APPROVED"

    file_ready = {"parents": [FOLDER_ID_READY_TO_PLAY]}
    assert status(file_ready) == "READY_TO_PLAY"

    file_other = {"parents": ["some_other_folder"]}
    assert status(file_other) is None

    file_no_parents = {}
    assert status(file_no_parents) is None


def test_update_tags_with_status_tag(mock_drive_service):
    """Test Tagger.update_tags with the status tag."""
    tagger = Tagger(mock_drive_service)
    file_to_tag = {"id": "file123", "parents": [FOLDER_ID_APPROVED]}

    tagger.update_tags(file_to_tag)

    expected_body = {"appProperties": {"status": "APPROVED"}}
    mock_drive_service.files.return_value.update.assert_called_once_with(
        fileId="file123", body=expected_body, fields="appProperties"
    )


def test_update_tags_no_update_if_tag_returns_none(mock_drive_service):
    """Test that no update is made if the tag function returns None."""
    tagger = Tagger(mock_drive_service)
    file_to_tag = {"id": "file123", "parents": ["other_folder"]}

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_with_multiple_tags(mock_drive_service):
    """Test that multiple tags are collected and applied."""

    @tag
    def another_tag(file):
        return "another_value"

    try:
        tagger = Tagger(mock_drive_service)
        file_to_tag = {"id": "file123", "parents": [FOLDER_ID_APPROVED]}

        tagger.update_tags(file_to_tag)

        expected_body = {
            "appProperties": {"status": "APPROVED", "another_tag": "another_value"}
        }

        # Use mock.call to check the body regardless of dict order
        update_call = mock_drive_service.files.return_value.update.call_args
        assert update_call.kwargs["fileId"] == "file123"
        assert update_call.kwargs["fields"] == "appProperties"
        assert update_call.kwargs["body"] == expected_body

    finally:
        # Clean up the dynamically added tag to not affect other tests
        from . import tags

        tags._TAGGERS.pop()


def test_update_tags_no_tags_defined(mock_drive_service):
    """Test behavior when no tags are defined (beyond the default status)."""
    # Temporarily clear taggers for this test
    from . import tags

    original_taggers = tags._TAGGERS
    tags._TAGGERS = []

    try:
        tagger = Tagger(mock_drive_service)
        file_to_tag = {"id": "file123", "parents": [FOLDER_ID_APPROVED]}
        tagger.update_tags(file_to_tag)
        mock_drive_service.files.return_value.update.assert_not_called()
    finally:
        tags._TAGGERS = original_taggers
