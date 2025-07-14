import pytest
from unittest.mock import Mock, patch, mock_open
import fitz
import cover


from googleapiclient.errors import HttpError


@pytest.fixture
def mock_google_services():
    """Create mock Google services (Docs and Drive)."""
    with patch("cover.default") as mock_default, patch("cover.build") as mock_build:
        mock_creds = Mock()
        mock_default.return_value = (mock_creds, None)

        mock_docs = Mock()
        mock_drive = Mock()
        mock_build.side_effect = lambda service, version, credentials: {
            "docs": mock_docs,
            "drive": mock_drive,
        }[service]

        yield {"docs": mock_docs, "drive": mock_drive, "creds": mock_creds}


def test_create_cover_from_template_basic(mock_google_services):
    """Test basic cover creation functionality."""
    docs = mock_google_services["docs"]
    drive = mock_google_services["drive"]

    # Mock the copy operation
    copy_response = {"id": "copy123", "name": "Copy of template"}
    drive.files.return_value.copy.return_value.execute.return_value = copy_response

    # Mock the batch update operation with normal response
    batch_response = {
        "replies": [
            {"replaceAllText": {"occurrencesChanged": 2}},
            {"replaceAllText": {"occurrencesChanged": 1}},
        ]
    }
    docs.documents.return_value.batchUpdate.return_value.execute.return_value = (
        batch_response
    )

    result = cover.create_cover_from_template(
        drive,
        docs,
        "template123",
        {"{{DATE}}": "1st January 2024", "{{TITLE}}": "Test Songbook"},
    )

    assert result == "copy123"

    # Verify copy was created
    drive.files.return_value.copy.assert_called_once_with(
        fileId="template123", body={"name": "Copy of template123"}
    )

    # Verify batch update was called
    docs.documents.return_value.batchUpdate.assert_called_once()
    call_args = docs.documents.return_value.batchUpdate.call_args
    assert call_args.kwargs["documentId"] == "copy123"

    # Verify the requests contain the replacements
    requests = call_args.kwargs["body"]["requests"]
    assert len(requests) == 2
    assert requests[0]["replaceAllText"]["containsText"]["text"] == "{{DATE}}"
    assert requests[0]["replaceAllText"]["replaceText"] == "1st January 2024"
    assert requests[1]["replaceAllText"]["containsText"]["text"] == "{{TITLE}}"
    assert requests[1]["replaceAllText"]["replaceText"] == "Test Songbook"


def test_create_cover_from_template_missing_occurrences_changed(
    mock_google_services, capsys
):
    """Test handling of missing occurrencesChanged key (the main bugfix)."""
    docs = mock_google_services["docs"]
    drive = mock_google_services["drive"]

    copy_response = {"id": "copy123", "name": "Copy of template"}
    drive.files.return_value.copy.return_value.execute.return_value = copy_response

    # Mock batch response with missing occurrencesChanged in some replies
    batch_response = {
        "replies": [
            {"replaceAllText": {"occurrencesChanged": 1}},  # Normal reply
            {"replaceAllText": {}},  # Missing occurrencesChanged
            {"someOtherReply": {}},  # Different reply type
            {"replaceAllText": {"occurrencesChanged": 2}},  # Another normal reply
        ]
    }
    docs.documents.return_value.batchUpdate.return_value.execute.return_value = (
        batch_response
    )

    # This should not raise a KeyError
    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"

    # Check the output includes the correct total (1 + 0 + 0 + 2 = 3)
    captured = capsys.readouterr()
    assert "Replaced 3 occurrences in the copy." in captured.out


def test_create_cover_from_template_no_replies(mock_google_services, capsys):
    """Test handling when there are no replies in the batch response."""
    docs = mock_google_services["docs"]
    drive = mock_google_services["drive"]

    copy_response = {"id": "copy123", "name": "Copy of template"}
    drive.files.return_value.copy.return_value.execute.return_value = copy_response

    # Mock batch response with no replies
    batch_response = {"replies": []}
    docs.documents.return_value.batchUpdate.return_value.execute.return_value = (
        batch_response
    )

    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"

    # Check the output shows 0 replacements
    captured = capsys.readouterr()
    assert "Replaced 0 occurrences in the copy." in captured.out


def test_create_cover_from_template_empty_replacement_map(mock_google_services):
    """Test with empty replacement map."""
    docs = mock_google_services["docs"]
    drive = mock_google_services["drive"]

    copy_response = {"id": "copy123", "name": "Copy of template"}
    drive.files.return_value.copy.return_value.execute.return_value = copy_response

    batch_response = {"replies": []}
    docs.documents.return_value.batchUpdate.return_value.execute.return_value = (
        batch_response
    )

    result = cover.create_cover_from_template(drive, docs, "template123", {})

    assert result == "copy123"

    # Verify batch update was called with empty requests
    call_args = docs.documents.return_value.batchUpdate.call_args
    requests = call_args.kwargs["body"]["requests"]
    assert len(requests) == 0


def test_create_cover_from_template_custom_title(mock_google_services):
    """Test creating cover with custom title."""
    docs = mock_google_services["docs"]
    drive = mock_google_services["drive"]

    copy_response = {"id": "copy123", "name": "Custom Title"}
    drive.files.return_value.copy.return_value.execute.return_value = copy_response

    batch_response = {"replies": []}
    docs.documents.return_value.batchUpdate.return_value.execute.return_value = (
        batch_response
    )

    result = cover.create_cover_from_template(
        drive,
        docs,
        "template123",
        {"{{DATE}}": "1st January 2024"},
        copy_title="Custom Title",
    )

    assert result == "copy123"

    # Verify copy was created with custom title
    drive.files.return_value.copy.assert_called_once_with(
        fileId="template123", body={"name": "Custom Title"}
    )


@patch("cover.config.load_cover_config")
@patch("cover.arrow.now")
def test_generate_cover_basic(mock_now, mock_load_cover_config):
    """Test basic cover generation functionality."""
    # Setup mocks
    mock_drive = Mock()
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"

    mock_load_cover_config.return_value = cover_file_id
    mock_now.return_value.format.return_value = "1st January 2024"

    # Mock PDF export
    pdf_content = b"fake pdf content"
    mock_drive.files.return_value.export.return_value.execute.return_value = pdf_content

    # Mock file operations
    with (
        patch("cover.os.makedirs"),
        patch("cover.open", mock_open()) as mock_file,
        patch("cover.fitz.open") as mock_fitz_open,
        patch("cover.create_cover_from_template") as mock_create_cover,
        patch("cover.default") as mock_default,
        patch("cover.build") as mock_build,
    ):
        mock_default.return_value = (Mock(), None)
        mock_build.return_value = mock_drive
        mock_create_cover.return_value = "temp_cover123"
        mock_pdf = Mock()
        mock_fitz_open.return_value = mock_pdf

        # Mock successful deletion
        mock_drive.files.return_value.delete.return_value.execute.return_value = {}

        result = cover.generate_cover(mock_cache_dir, cover_file_id)

        assert result == mock_pdf

        # Verify cover was created with date
        mock_create_cover.assert_called_once_with(
            mock_drive, mock_drive, cover_file_id, {"{{DATE}}": "1st January 2024"}
        )

        # Verify PDF was exported
        mock_drive.files.return_value.export.assert_called_once_with(
            fileId="temp_cover123", mimeType="application/pdf"
        )

        # Verify file was written
        mock_file.assert_called_once()
        mock_file().write.assert_called_once_with(pdf_content)

        # Verify temporary file was deleted
        mock_drive.files.return_value.delete.assert_called_once_with(
            fileId="temp_cover123"
        )


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
        patch("cover.default") as mock_default,
        patch("cover.build") as mock_build,
    ):
        mock_default.return_value = (Mock(), None)
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
        patch("cover.default") as mock_default,
        patch("cover.build") as mock_build,
    ):
        mock_default.return_value = (Mock(), None)
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
        patch("cover.default") as mock_default,
        patch("cover.build") as mock_build,
    ):
        mock_default.return_value = (Mock(), None)
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


def test_create_cover_malformed_batch_response(mock_google_services, capsys):
    """Test handling of malformed batch response structure."""
    docs = mock_google_services["docs"]
    drive = mock_google_services["drive"]

    copy_response = {"id": "copy123", "name": "Copy of template"}
    drive.files.return_value.copy.return_value.execute.return_value = copy_response

    # Mock malformed batch response
    batch_response = {
        "replies": [
            {"replaceAllText": {"occurrencesChanged": 1}},
            {"replaceAllText": None},  # Null replaceAllText
            None,  # Null reply
            {"replaceAllText": {"occurrencesChanged": "invalid"}},  # Invalid type
        ]
    }
    docs.documents.return_value.batchUpdate.return_value.execute.return_value = (
        batch_response
    )

    # Should handle malformed responses gracefully
    result = cover.create_cover_from_template(
        drive, docs, "template123", {"{{DATE}}": "1st January 2024"}
    )

    assert result == "copy123"

    # Should only count the valid occurrence
    captured = capsys.readouterr()
    assert "Replaced 1 occurrences in the copy." in captured.out
