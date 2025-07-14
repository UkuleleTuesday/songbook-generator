import json
import pytest
from unittest.mock import Mock, patch, mock_open
import fitz
import cover


from googleapiclient.errors import HttpError
from googleapiclient.http import HttpMockSequence


def test_create_cover_from_template_basic():
    """Test basic cover creation functionality."""
    http = HttpMockSequence(
        [
            (
                {"status": "200"},
                json.dumps({"id": "root_id"}),
            ),
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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

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
    drive = cover.build("drive", "v3", http=http)
    docs = cover.build("docs", "v1", http=http)

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


@patch("cover.config.load_cover_config", return_value="cover123")
@patch("cover.arrow.now")
def test_generate_cover_basic(mock_now, mock_load_cover_config):
    """Test basic cover generation functionality."""
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"
    mock_now.return_value.format.return_value = "1st January 2024"
    pdf_content = b"fake pdf content"
    http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, json.dumps({"replies": []})),
            ({"status": "200"}, pdf_content),
            ({"status": "200"}, ""),
        ]
    )

    with (
        patch("cover.os.makedirs"),
        patch("cover.open", mock_open()) as mock_file,
        patch("cover.fitz.open") as mock_fitz_open,
        patch("cover.get_credentials"),
        patch("cover.build", return_value=Mock(http=http)),
    ) as mock_build:
        mock_pdf = Mock()
        mock_fitz_open.return_value = mock_pdf

        result = cover.generate_cover(mock_cache_dir, cover_file_id, http=http)

        assert result == mock_pdf
        mock_file().write.assert_called_once_with(pdf_content)


@patch("cover.config.load_cover_config")
@patch("cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo, mock_load_cover_config):
    """Test when no cover file is configured."""
    mock_load_cover_config.return_value = None
    mock_cache_dir = "/tmp/cache"

    result = cover.generate_cover(mock_cache_dir)

    assert result is None
    mock_echo.assert_called_once_with(
        "No cover file ID configured. Skipping cover generation."
    )


@patch("cover.config.load_cover_config")
@patch("cover.arrow.now")
def test_generate_cover_corrupted_pdf(mock_now, mock_load_cover_config):
    """Test handling of corrupted PDF file."""
    mock_drive = Mock()
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"

    mock_load_cover_config.return_value = cover_file_id
    mock_now.return_value.format.return_value = "1st January 2024"

    pdf_content = b"corrupted pdf content"
    mock_drive.files.return_value.export.return_value.execute.return_value = pdf_content

    with (
        patch("cover.os.makedirs"),
        patch("cover.open", mock_open()),
        patch("cover.fitz.open") as mock_fitz_open,
        patch("cover.create_cover_from_template") as mock_create_cover,
        patch("cover.get_credentials") as mock_get_credentials,
        patch("cover.build") as mock_build,
    ):
        mock_get_credentials.return_value = Mock()
        mock_build.return_value = mock_drive
        mock_create_cover.return_value = "temp_cover123"
        mock_fitz_open.side_effect = fitz.EmptyFileError("Empty file")

        with pytest.raises(ValueError, match="Downloaded cover file is corrupted"):
            cover.generate_cover(mock_cache_dir, cover_file_id)


@patch("cover.config.load_cover_config")
@patch("cover.arrow.now")
def test_generate_cover_deletion_failure(mock_now, mock_load_cover_config):
    """Test handling when temporary file deletion fails."""
    mock_drive = Mock()
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"

    mock_load_cover_config.return_value = cover_file_id
    mock_now.return_value.format.return_value = "1st January 2024"

    pdf_content = b"fake pdf content"
    mock_drive.files.return_value.export.return_value.execute.return_value = pdf_content

    with (
        patch("cover.os.makedirs"),
        patch("cover.open", mock_open()),
        patch("cover.fitz.open") as mock_fitz_open,
        patch("cover.create_cover_from_template") as mock_create_cover,
        patch("cover.get_credentials") as mock_get_credentials,
        patch("cover.build") as mock_build,
    ):
        mock_get_credentials.return_value = Mock()
        mock_build.return_value = mock_drive
        mock_create_cover.return_value = "temp_cover123"
        mock_pdf = Mock()
        mock_fitz_open.return_value = mock_pdf

        # Mock deletion failure
        mock_drive.files.return_value.delete.return_value.execute.side_effect = (
            HttpError(Mock(status=500), b"API Error")
        )

        with pytest.raises(cover.CoverGenerationException):
            cover.generate_cover(mock_cache_dir, cover_file_id)


@patch("cover.arrow.now")
def test_generate_cover_uses_provided_cover_id(mock_now):
    """Test that provided cover_file_id takes precedence over config."""
    mock_drive = Mock()
    mock_cache_dir = "/tmp/cache"
    provided_cover_id = "provided_cover123"

    mock_now.return_value.format.return_value = "1st January 2024"

    pdf_content = b"fake pdf content"
    mock_drive.files.return_value.export.return_value.execute.return_value = pdf_content

    with (
        patch("cover.config.load_cover_config") as mock_load_cover_config,
        patch("cover.os.makedirs"),
        patch("cover.open", mock_open()),
        patch("cover.fitz.open") as mock_fitz_open,
        patch("cover.create_cover_from_template") as mock_create_cover,
        patch("cover.get_credentials") as mock_get_credentials,
        patch("cover.build") as mock_build,
    ):
        mock_get_credentials.return_value = Mock()
        mock_build.return_value = mock_drive
        mock_load_cover_config.return_value = (
            "config_cover123"  # This should be ignored
        )
        mock_create_cover.return_value = "temp_cover123"
        mock_pdf = Mock()
        mock_fitz_open.return_value = mock_pdf
        mock_drive.files.return_value.delete.return_value.execute.return_value = {}

        cover.generate_cover(mock_cache_dir, provided_cover_id)

        # Config should not be loaded when cover_file_id is provided
        mock_load_cover_config.assert_not_called()

        # Check that the provided_cover_id was used
        mock_create_cover.assert_called_with(
            mock_drive, mock_drive, provided_cover_id, {"{{DATE}}": "1st January 2024"}
        )


def test_create_cover_malformed_batch_response(capsys):
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
