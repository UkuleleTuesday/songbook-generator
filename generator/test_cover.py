import json
import pytest
from unittest.mock import Mock, patch, mock_open
import fitz
import cover


from googleapiclient.errors import HttpError
from googleapiclient.http import HttpMockSequence




@patch("cover.build")
def test_create_cover_from_template_basic(mock_build):
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive,
        docs,
        "template123",
        {"{{DATE}}": "1st January 2024", "{{TITLE}}": "Test Songbook"},
    )

    assert result == "copy123"


@patch("cover.build")
def test_create_cover_from_template_missing_occurrences_changed(mock_build, capsys):
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"
    captured = capsys.readouterr()
    assert "Replaced 3 occurrences in the copy." in captured.out


@patch("cover.build")
def test_create_cover_from_template_no_replies(mock_build, capsys):
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"
    captured = capsys.readouterr()
    assert "Replaced 0 occurrences in the copy." in captured.out


@patch("cover.build")
def test_create_cover_from_template_empty_replacement_map(mock_build):
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

    result = cover.create_cover_from_template(drive, docs, "template123", {})

    assert result == "copy123"


@patch("cover.build")
def test_create_cover_from_template_custom_title(mock_build):
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

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
    mock_now, mock_open_file, mock_makedirs, mock_get_credentials, mock_build, mock_fitz
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
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )

    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_drive.files().export().execute.return_value = pdf_content
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]

    mock_pdf = Mock()
    mock_fitz.return_value = mock_pdf
    result = cover.generate_cover("/tmp/cache", "cover123")

    assert result == mock_pdf
    mock_open_file().write.assert_called_once_with(pdf_content)


@patch("cover.config.load_cover_config")
@patch("cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo, mock_load_config):
    """Test when no cover file is configured."""
    mock_load_config.return_value = None
    result = cover.generate_cover("/tmp/cache")
    assert result is None
    mock_echo.assert_called_once_with(
        "No cover file ID configured. Skipping cover generation."
    )


@patch("cover.fitz.open")
@patch("cover.build")
def test_generate_cover_corrupted_pdf(mock_build, mock_fitz):
    """Test handling of corrupted PDF file."""
    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )
    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_drive.files().export().execute.return_value = b"corrupted"
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.side_effect = fitz.EmptyFileError("Empty file")

    with pytest.raises(
        cover.CoverGenerationException, match="Downloaded cover file is corrupted"
    ):
        cover.generate_cover("/tmp/cache", "cover123")


@patch("cover.fitz.open")
@patch("cover.build")
def test_generate_cover_deletion_failure(mock_build, mock_fitz):
    """Test handling when temporary file deletion fails."""
    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            (Mock(status=500), b"API Error"),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )
    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_drive.files().export().execute.return_value = b"pdf content"
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.return_value = Mock()

    with pytest.raises(cover.CoverGenerationException):
        cover.generate_cover("/tmp/cache", "cover123")


@patch("cover.config.load_cover_config")
@patch("cover.fitz.open")
@patch("cover.build")
def test_generate_cover_uses_provided_cover_id(
    mock_build, mock_fitz, mock_load_config
):
    """Test that provided cover_file_id takes precedence over config."""
    pdf_content = b"fake pdf content"
    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, ""),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )
    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_drive.files().export().execute.return_value = pdf_content
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.return_value = Mock()

    cover.generate_cover("/tmp/cache", "provided_cover123")

    mock_load_config.assert_not_called()


@patch("cover.build")
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"
    captured = capsys.readouterr()
    assert "Replaced 1 occurrences in the copy." in captured.out
