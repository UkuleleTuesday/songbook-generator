from unittest.mock import Mock

import pytest

from ..worker.models import File
from .tags import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    Tagger,
    status,
    tag,
    Context,
    chords,
)


@pytest.fixture
def mock_drive_service():
    """Create a mock Google Drive service object."""
    return Mock()


def test_status_tagger():
    """Test the status tag function logic."""
    file_approved = File(id="1", name="f1", parents=[FOLDER_ID_APPROVED])
    assert status(Context(file=file_approved)) == "APPROVED"

    file_ready = File(id="2", name="f2", parents=[FOLDER_ID_READY_TO_PLAY])
    assert status(Context(file=file_ready)) == "READY_TO_PLAY"

    file_other = File(id="3", name="f3", parents=["some_other_folder"])
    assert status(Context(file=file_other)) is None

    file_no_parents = File(id="4", name="f4")
    assert status(Context(file=file_no_parents)) is None


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


def test_chords_tagger(mocker):
    """Test the chords tag function logic."""
    # Mock the Google Docs API response
    mock_doc_content = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {
                                "textRun": {
                                    "content": "(C)",
                                    "textStyle": {"bold": True},
                                }
                            },
                            {
                                "textRun": {
                                    "content": "some text",
                                    "textStyle": {},
                                }
                            },
                            {
                                "textRun": {
                                    "content": "(G7)",
                                    "textStyle": {"bold": True},
                                }
                            },
                        ]
                    }
                },
                {
                    "paragraph": {
                        "elements": [
                            {
                                "textRun": {
                                    "content": "(Am)",
                                    "textStyle": {"bold": True},
                                }
                            },
                            {
                                "textRun": {
                                    "content": "(C)",  # Duplicate
                                    "textStyle": {"bold": True},
                                }
                            },
                        ]
                    }
                },
            ]
        }
    }

    mock_docs_service = Mock()
    mock_docs_service.documents.return_value.get.return_value.execute.return_value = (
        mock_doc_content
    )
    mocker.patch(
        "generator.tagupdater.tags.build", return_value=mock_docs_service
    )

    # File must be a Google Doc
    file = File(
        id="doc1", name="song.gdoc", mimeType="application/vnd.google-apps.document"
    )
    tagger = Tagger(Mock())
    context = Context(file=file, document=tagger.docs_service.documents().get(documentId=file.id).execute())
    
    result = chords(context)

    # Chords should be unique and in order of appearance
    assert result == "C,G7,Am"

    # Test with non-doc file
    pdf_file = File(id="doc2", name="song.pdf", mimeType="application/pdf")
    context_pdf = Context(file=pdf_file)
    assert chords(context_pdf) is None


def test_update_tags_no_update_if_tag_returns_none(mock_drive_service):
    """Test that no update is made if the tag function returns None."""
    tagger = Tagger(mock_drive_service)
    file_to_tag = File(id="file123", name="test.pdf", parents=["other_folder"])

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_no_update_if_tags_are_identical(mock_drive_service):
    """Test that no update is made if the generated tags match existing ones."""
    tagger = Tagger(mock_drive_service)
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={"status": "APPROVED"},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_with_multiple_tags_and_preserves_existing(mock_drive_service):
    """Test that multiple tags are applied and existing properties preserved."""

    @tag
    def another_tag(ctx: Context) -> str:
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
