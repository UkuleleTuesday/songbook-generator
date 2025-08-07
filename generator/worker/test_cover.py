import json
import pytest
from unittest.mock import Mock, patch
import fitz
from . import cover
from ..common import config

from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence


@patch("generator.worker.cover.click.echo")
def test_apply_template_replacements_permission_error(mock_echo):
    """Test that a permission error is handled gracefully."""
    docs_http = HttpMockSequence([({"status": "403"}, "Permission denied")])
    docs = build("docs", "v1", http=docs_http)
    mock_config = config.Cover(file_id="doc123")
    generator = cover.CoverGenerator(Mock(), Mock(), docs, mock_config)

    generator._apply_template_replacements("doc123", {"{{PLACEHOLDER}}": "value"})

    mock_echo.assert_called_once()
    assert "Warning: Could not apply template" in mock_echo.call_args[0][0]


@patch("generator.worker.cover.gdrive.download_file")
@patch("generator.worker.cover.CoverGenerator._apply_template_replacements")
def test_generate_cover_with_templating(mock_apply_replacements, mock_download):
    """Test that templating is applied, reverted, and PDF is exported."""
    mock_drive = Mock()
    mock_docs = Mock()
    mock_cache = Mock()
    mock_download.return_value = b"fake-pdf-content"  # Fix for fitz.open
    mock_config = config.Cover(file_id="cover123")

    generator = cover.CoverGenerator(
        mock_cache, mock_drive, mock_docs, mock_config, enable_templating=True
    )
    with patch("fitz.open"):
        generator.generate_cover("cover123")

    # Check that replacements were applied and then reverted
    assert mock_apply_replacements.call_count == 2
    mock_download.assert_called_once_with(
        mock_drive,
        "cover123",
        "Cover-cover123",
        mock_cache,
        "covers",
        "application/pdf",
        export=True,
    )


@patch("generator.worker.cover.fitz.open")
@patch("generator.worker.cover.build")
@patch("generator.worker.cover.get_credentials")
@patch("generator.worker.cover.arrow.now")
def test_generate_cover_basic(
    mock_now,
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
            (
                {"status": "200"},
                json.dumps({"modifiedTime": "2024-01-01T00:00:00Z"}),
            ),
            ({"status": "200"}, pdf_content),
        ]
    )
    docs_http = HttpMockSequence(
        [
            (
                {"status": "200"},
                json.dumps({"replies": []}),
            ),
            (
                {"status": "200"},
                json.dumps({"replies": []}),
            ),
        ]
    )
    mock_drive = build("drive", "v3", http=drive_http)
    mock_docs = build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]

    mock_pdf = Mock()
    # Set page_count to 0 to prevent iteration in normalize_pdf_fonts
    mock_pdf.page_count = 0
    mock_fitz.return_value = mock_pdf
    with patch("generator.common.caching.LocalStorageCache") as mock_cache:
        mock_cache.get.return_value = None
        result = cover.generate_cover(mock_cache, "cover123")

    assert result == mock_pdf


@patch("generator.worker.cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo):
    """Test when no cover file is configured."""
    mock_config = config.Cover(file_id=None)
    generator = cover.CoverGenerator(Mock(), Mock(), Mock(), mock_config)
    result = generator.generate_cover()

    assert result is None
    mock_echo.assert_called_once_with(
        "No cover file ID configured. Skipping cover generation."
    )


@patch("generator.worker.cover.gdrive.download_file")
@patch("generator.worker.cover.fitz.open")
@patch("generator.worker.cover.build")
@patch("generator.worker.cover.get_credentials")
def test_generate_cover_templating_disabled(
    mock_get_credentials,
    mock_build,
    mock_fitz,
    mock_download_file,
):
    """Test cover generation with templating disabled."""
    mock_drive = Mock()
    mock_docs = Mock()
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]

    mock_pdf_data = b"fake pdf data"
    mock_download_file.return_value = mock_pdf_data
    mock_pdf = Mock()
    mock_fitz.return_value = mock_pdf
    mock_cache = Mock()
    mock_config = config.Cover(file_id="cover123")

    # Now we can test the real CoverGenerator logic
    generator = cover.CoverGenerator(
        mock_cache, mock_drive, mock_docs, mock_config, enable_templating=False
    )
    result = generator.generate_cover("cover123")

    assert result == mock_pdf
    mock_download_file.assert_called_once_with(
        mock_drive,
        "cover123",
        "Cover-cover123",
        mock_cache,
        "covers",
        "application/pdf",
        export=False,
    )
    mock_fitz.assert_called_once_with(stream=mock_pdf_data, filetype="pdf")


@patch("generator.worker.cover.get_credentials")
@patch("generator.worker.cover.fitz.open")
@patch("generator.worker.cover.build")
def test_generate_cover_corrupted_pdf(
    mock_build, mock_fitz, mock_get_credentials, tmp_path
):
    """Test handling of corrupted PDF file."""
    pdf_content = b"corrupted"
    drive_http = HttpMockSequence(
        [
            (
                {"status": "200"},
                json.dumps({"modifiedTime": "2024-01-01T00:00:00Z"}),
            ),
            ({"status": "200"}, pdf_content),
        ]
    )
    docs_http = HttpMockSequence(
        [
            (
                {"status": "200"},
                json.dumps({"replies": []}),
            ),
            (
                {"status": "200"},
                json.dumps({"replies": []}),
            ),
        ]
    )
    mock_drive = build("drive", "v3", http=drive_http)
    mock_docs = build("docs", "v1", http=docs_http)
    mock_build.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_fitz.side_effect = fitz.EmptyFileError("Empty file")

    with (
        pytest.raises(
            cover.CoverGenerationException, match="Downloaded cover file is corrupted"
        ),
        patch("generator.common.caching.LocalStorageCache") as mock_cache,
    ):
        mock_cache.get.return_value = None
        cover.generate_cover(mock_cache, "cover123")


@patch("generator.worker.cover.gdrive.download_file")
@patch("generator.worker.cover.CoverGenerator._apply_template_replacements")
def test_generate_cover_uses_provided_cover_id(mock_apply_replacements, mock_download):
    """Test that a provided cover_file_id is used instead of the one from config."""
    # This config has a different file_id
    mock_config = config.Cover(file_id="config_cover_id")

    # Mock services
    mock_drive = Mock()
    mock_docs = Mock()
    mock_cache = Mock()
    mock_download.return_value = b"fake-pdf-content"

    generator = cover.CoverGenerator(
        mock_cache, mock_drive, mock_docs, mock_config, enable_templating=True
    )

    with patch("fitz.open"):
        # Call generate_cover with a specific file_id
        generator.generate_cover(cover_file_id="provided_cover_id")

    # Assert that download_file was called with the provided_cover_id, not the one from config
    mock_download.assert_called_once()
    called_args = mock_download.call_args[0]
    assert called_args[1] == "provided_cover_id"
