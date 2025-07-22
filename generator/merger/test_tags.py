from unittest.mock import Mock

import pytest

from ..worker.models import File
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
    file_approved = File(id="1", name="f1", parents=[FOLDER_ID_APPROVED])
    assert status(file_approved) == "APPROVED"

    file_ready = File(id="2", name="f2", parents=[FOLDER_ID_READY_TO_PLAY])
    assert status(file_ready) == "READY_TO_PLAY"

    file_other = File(id="3", name="f3", parents=["some_other_folder"])
    assert status(file_other) is None

    file_no_parents = File(id="4", name="f4")
    assert status(file_no_parents) is None


def test_update_tags_with_status_tag(mock_drive_service):
    """Test Tagger.update_tags with the status tag."""
    tagger = Tagger(mock_drive_service)
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )

    tagger.update_tags(file_to_tag)

    expected_body = {"properties": {"status": "APPROVED"}}
    mock_drive_service.files.return_value.update.assert_called_once_with(
        fileId="file123", body=expected_body, fields="properties"
    )


def test_update_tags_no_update_if_tag_returns_none(mock_drive_service):
    """Test that no update is made if the tag function returns None."""
    tagger = Tagger(mock_drive_service)
    file_to_tag = File(id="file123", name="test.pdf", parents=["other_folder"])

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_with_multiple_tags_and_preserves_existing(mock_drive_service):
    """Test that multiple tags are applied and existing properties preserved."""

    @tag
    def another_tag(file):
        return "another_value"

    try:
        tagger = Tagger(mock_drive_service)
        file_to_tag = File(
            id="file123",
            name="test.pdf",
            parents=[FOLDER_ID_APPROVED],
            properties={"existing_prop": "existing_value"},
        )

        tagger.update_tags(file_to_tag)

        expected_properties = {
            "status": "APPROVED",
            "another_tag": "another_value",
            "existing_prop": "existing_value",
        }
        expected_body = {"properties": expected_properties}

        mock_drive_service.files.return_value.update.assert_called_once_with(
            fileId="file123", body=expected_body, fields="properties"
        )

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
        file_to_tag = File(
            id="file123",
            name="test.pdf",
            parents=[FOLDER_ID_APPROVED],
        )
        tagger.update_tags(file_to_tag)
        mock_drive_service.files.return_value.update.assert_not_called()
    finally:
        tags._TAGGERS = original_taggers
