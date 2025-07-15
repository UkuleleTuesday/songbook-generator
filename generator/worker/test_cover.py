import json
import pytest
from unittest.mock import Mock, patch, mock_open
import fitz
from . import cover

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpMockSequence


def test_create_cover_from_template_basic():
    """Test basic cover creation functionality."""
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "copy123", "name": "Copy of template"}),
            ),
            (
                {"status": "200"},
                json.dumps(
                    {
                        "replies": [
                            {"replaceAllText": {"occurrencesChanged": 2}},
                            {"replaceAllText": {"occurrencesChanged": 1}},
                        ]
                    }
                ),
            ),
        ]
    )
    drive = build("drive", "v3", http=http)
    docs = build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive,
        docs,
        "template123",
        {"{{DATE}}": "1st January 2024", "{{TITLE}}": "Test Songbook"},
    )

    assert result == "copy123"


def test_create_cover_from_template_missing_occurrences_changed(capsys):
    """Test handling of missing occurrencesChanged key (the main bugfix)."""
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "copy123", "name": "Copy of template"}),
            ),
            (
                {"status": "200"},
                json.dumps(
                    {
                        "replies": [
                            {"replaceAllText": {"occurrencesChanged": 1}},
                            {"replaceAllText": {}},
                            {"someOtherReply": {}},
                            {"replaceAllText": {"occurrencesChanged": 2}},
                        ]
                    }
                ),
            ),
        ]
    )
    drive = build("drive", "v3", http=http)
    docs = build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"
    captured = capsys.readouterr()
    assert "Replaced 3 occurrences in the copy." in captured.out


def test_create_cover_from_template_no_replies(capsys):
    """Test handling when there are no replies in the batch response."""
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "copy123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, json.dumps({"replies": []})),
        ]
    )
    drive = build("drive", "v3", http=http)
    docs = build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"
    captured = capsys.readouterr()
    assert "Replaced 0 occurrences in the copy." in captured.out


def test_create_cover_from_template_empty_replacement_map():
    """Test with empty replacement map."""
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "copy123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, json.dumps({"replies": []})),
        ]
    )
    drive = build("drive", "v3", http=http)
    docs = build("docs", "v1", http=http)

    result = cover.create_cover_from_template(drive, docs, "template123", {})

    assert result == "copy123"


def test_create_cover_from_template_custom_title():
    """Test creating cover with custom title."""
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "copy123", "name": "Custom Title"}),
            ),
            ({"status": "200"}, json.dumps({"replies": []})),
        ]
    )
    drive = build("drive", "v3", http=http)
    docs = build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive,
        docs,
        "template123",
        {"{{DATE}}": "1st January 2024"},
        copy_title="Custom Title",
    )

    assert result == "copy123"


@patch("cover.fitz.open")
@patch("cover.build")
@patch("cover.get_credentials")
@patch("cover.os.makedirs")
@patch("cover.open", new_callable=mock_open)
@patch("cover.arrow.now")
def test_generate_cover_basic(
    mock_now,
    mock_open_file,
    mock_makedirs,
    mock_get_credentials,
    mock_build,
    mock_fitz,
    tmp_path,
):
    """Test basic cover generation functionality."""
    mock_now.return_value.format.return_value = "1st January 2024"
    pdf_content = b"fake pdf content"
    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, ""),  # for the delete call
        ]
    )
    docs_http = HttpMockSequence([({"status": "200"}, json.dumps({"replies": []}))])

    mock_drive = build("drive", "v3", http=drive_http)
    mock_drive.files().export().execute.return_value = pdf_content
    mock_docs = build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]

    mock_pdf = Mock()
    mock_fitz.return_value = mock_pdf
    result = cover.generate_cover(tmp_path, "cover123")

    assert result == mock_pdf
    mock_open_file().write.assert_called_once_with(pdf_content)


@patch("generator.worker.cover.config.load_cover_config")
@patch("generator.worker.cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo, mock_load_config, tmp_path):
    """Test when no cover file is configured."""
    mock_load_config.return_value = None
    result = cover.generate_cover(tmp_path)
    assert result is None
    mock_echo.assert_called_once_with(
        "No cover file ID configured. Skipping cover generation."
    )


@patch("generator.worker.cover.get_credentials")
@patch("generator.worker.cover.fitz.open")
@patch("generator.worker.cover.build")
def test_generate_cover_corrupted_pdf(
    mock_build, mock_fitz, mock_get_credentials, tmp_path
):
    """Test handling of corrupted PDF file."""
    mock_drive = Mock()
    mock_drive.files().get().execute.return_value = {"id": "root_id"}
    mock_drive.files().copy().execute.return_value = {
        "id": "temp_cover123",
        "name": "Copy of template",
    }
    mock_drive.files().export().execute.return_value = b"corrupted"

    mock_docs = Mock()
    mock_docs.documents().batchUpdate().execute.return_value = {"replies": []}
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.side_effect = fitz.EmptyFileError("Empty file")

    with pytest.raises(
        cover.CoverGenerationException, match="Downloaded cover file is corrupted"
    ):
        cover.generate_cover(tmp_path, "cover123")


@patch("generator.worker.cover.get_credentials")
@patch("generator.worker.cover.fitz.open")
@patch("generator.worker.cover.build")
def test_generate_cover_deletion_failure(
    mock_build, mock_fitz, mock_get_credentials, tmp_path
):
    """Test handling when temporary file deletion fails."""
    mock_drive = Mock()
    mock_drive.files().get().execute.return_value = {"id": "root_id"}
    mock_drive.files().copy().execute.return_value = {
        "id": "temp_cover123",
        "name": "Copy of template",
    }
    mock_drive.files().export().execute.return_value = b"pdf content"
    mock_drive.files().delete().execute.side_effect = HttpError(Mock(), b"API Error")

    mock_docs = Mock()
    mock_docs.documents().batchUpdate().execute.return_value = {"replies": []}

    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.return_value = Mock()

    with pytest.raises(cover.CoverGenerationException):
        cover.generate_cover(tmp_path, "cover123")


@patch("generator.worker.cover.config.load_cover_config")
@patch("generator.worker.cover.fitz.open")
@patch("generator.worker.cover.build")
@patch("generator.worker.cover.get_credentials")
def test_generate_cover_uses_provided_cover_id(
    mock_get_credentials, mock_build, mock_fitz, mock_load_config, tmp_path
):
    """Test that provided cover_file_id takes precedence over config."""
    mock_drive = Mock()
    mock_drive.files().get().execute.return_value = {"id": "root_id"}
    mock_drive.files().copy().execute.return_value = {
        "id": "temp_cover123",
        "name": "Copy of template",
    }
    mock_drive.files().export().execute.return_value = b"fake pdf content"
    mock_drive.files().delete().execute.return_value = {}

    mock_docs = Mock()
    mock_docs.documents().batchUpdate().execute.return_value = {"replies": []}

    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.return_value = Mock()

    cover.generate_cover(tmp_path, "provided_cover123")

    mock_load_config.assert_not_called()


@patch("generator.worker.cover.build")
def test_create_cover_malformed_batch_response(mock_build, capsys):
    """Test handling of malformed batch response structure."""
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "copy123", "name": "Copy of template"}),
            ),
            (
                {"status": "200"},
                json.dumps(
                    {
                        "replies": [
                            {"replaceAllText": {"occurrencesChanged": 1}},
                            {"replaceAllText": None},
                            None,
                            {"replaceAllText": {"occurrencesChanged": "invalid"}},
                        ]
                    }
                ),
            ),
        ]
    )
    drive = build("drive", "v3", http=http)
    docs = build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"
    captured = capsys.readouterr()
    assert "Replaced 1 occurrences in the copy." in captured.out
