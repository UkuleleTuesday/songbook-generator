import json
import arrow
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
    generator = cover.CoverGenerator(
        gdrive_client=Mock(spec=cover.GoogleDriveClient),
        docs_service=docs,
        cover_config=mock_config,
    )

    generator._apply_template_replacements("doc123", {"{{PLACEHOLDER}}": "value"})

    mock_echo.assert_called_once()
    assert "Warning: Could not apply template" in mock_echo.call_args[0][0]


@patch("generator.common.gdrive.GoogleDriveClient.download_file")
@patch("generator.worker.cover.CoverGenerator._apply_template_replacements")
def test_generate_cover_with_templating(mock_apply_replacements, mock_download_file):
    """Test that templating is applied, reverted, and PDF is exported."""
    mock_gdrive_client = Mock(spec=cover.GoogleDriveClient)
    mock_docs = Mock()
    mock_download_file.return_value = b"fake-pdf-content"  # Fix for fitz.open
    mock_apply_replacements.return_value = {"{{DATE}}": 1, "{{NEXT_TUESDAY}}": 1}
    mock_config = config.Cover(file_id="cover123")

    generator = cover.CoverGenerator(
        mock_gdrive_client, mock_docs, mock_config, enable_templating=True
    )
    with patch("fitz.open"):
        generator.generate_cover("cover123")

    # Check that replacements were applied and then reverted
    assert mock_apply_replacements.call_count == 2
    mock_gdrive_client.download_file.assert_called_once_with(
        file_id="cover123",
        file_name="Cover-cover123",
        cache_prefix="covers",
        mime_type="application/pdf",
        export=True,
    )


@patch("generator.worker.cover.get_credentials", return_value=(Mock(), None))
@patch("generator.worker.cover.build")
@patch("generator.worker.cover.GoogleDriveClient")
@patch("generator.worker.cover.CoverGenerator")
@patch("generator.worker.cover.arrow.now")
def test_generate_cover_basic(
    mock_now,
    mock_cover_generator_class,
    mock_gdrive_client_class,
    mock_build,
    mock_get_credentials,
    tmp_path,
):
    """Test basic cover generation functionality."""
    mock_now.return_value.format.return_value = "1st January 2024"
    mock_generator_instance = mock_cover_generator_class.return_value
    mock_pdf = Mock(spec=fitz.Document)
    mock_generator_instance.generate_cover.return_value = mock_pdf

    with patch("generator.common.caching.LocalStorageCache") as mock_cache_class:
        mock_cache_instance = mock_cache_class.return_value
        result = cover.generate_cover(mock_cache_instance, "cover123")

    assert result == mock_pdf
    mock_cover_generator_class.assert_called_once()
    mock_generator_instance.generate_cover.assert_called_once_with("cover123")


@patch("generator.worker.cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo):
    """Test when no cover file is configured."""
    mock_config = config.Cover(file_id=None)
    generator = cover.CoverGenerator(
        gdrive_client=Mock(spec=cover.GoogleDriveClient),
        docs_service=Mock(),
        cover_config=mock_config,
    )
    result = generator.generate_cover()

    assert result is None
    mock_echo.assert_called_once_with(
        "No cover file ID configured. Skipping cover generation."
    )


@patch("generator.worker.cover.fitz.open")
def test_generate_cover_templating_disabled(mock_fitz):
    """Test cover generation with templating disabled."""
    mock_gdrive_client = Mock(spec=cover.GoogleDriveClient)
    mock_docs = Mock()

    mock_pdf_data = b"fake pdf data"
    mock_gdrive_client.download_file.return_value = mock_pdf_data
    mock_pdf = Mock()
    mock_fitz.return_value = mock_pdf
    mock_config = config.Cover(file_id="cover123")

    # Now we can test the real CoverGenerator logic
    generator = cover.CoverGenerator(
        mock_gdrive_client, mock_docs, mock_config, enable_templating=False
    )
    result = generator.generate_cover("cover123")

    assert result == mock_pdf
    mock_gdrive_client.download_file.assert_called_once_with(
        file_id="cover123",
        file_name="Cover-cover123",
        cache_prefix="covers",
        mime_type="application/pdf",
        export=False,
    )
    mock_fitz.assert_called_once_with(stream=mock_pdf_data, filetype="pdf")


@patch("generator.worker.cover.get_credentials", return_value=(Mock(), None))
@patch("generator.worker.cover.build")
@patch("generator.worker.cover.GoogleDriveClient")
@patch("generator.worker.cover.CoverGenerator")
def test_generate_cover_corrupted_pdf(
    mock_cover_generator_class,
    mock_gdrive_client_class,
    mock_build,
    mock_get_credentials,
    tmp_path,
):
    """Test handling of corrupted PDF file."""
    mock_generator_instance = mock_cover_generator_class.return_value
    mock_generator_instance.generate_cover.side_effect = cover.CoverGenerationException(
        "Downloaded cover file is corrupted."
    )

    with (
        pytest.raises(
            cover.CoverGenerationException, match="Downloaded cover file is corrupted"
        ),
        patch("generator.common.caching.LocalStorageCache") as mock_cache_class,
    ):
        mock_cache_instance = mock_cache_class.return_value
        cover.generate_cover(mock_cache_instance, "cover123")


@patch("generator.common.gdrive.GoogleDriveClient.download_file")
@patch("generator.worker.cover.CoverGenerator._apply_template_replacements")
def test_generate_cover_uses_provided_cover_id(
    mock_apply_replacements, mock_download_file
):
    """Test that a provided cover_file_id is used instead of the one from config."""
    # This config has a different file_id
    mock_config = config.Cover(file_id="config_cover_id")

    # Mock services
    mock_gdrive_client = Mock(spec=cover.GoogleDriveClient)
    mock_docs = Mock()
    mock_download_file.return_value = b"fake-pdf-content"
    mock_apply_replacements.return_value = {"{{NEXT_TUESDAY}}": 1}

    generator = cover.CoverGenerator(
        mock_gdrive_client, mock_docs, mock_config, enable_templating=True
    )

    with patch("fitz.open"):
        # Call generate_cover with a specific file_id
        generator.generate_cover(cover_file_id="provided_cover_id")

    # Assert that download_file was called with the provided_cover_id, not the one from config
    mock_gdrive_client.download_file.assert_called_once()
    called_kwargs = mock_gdrive_client.download_file.call_args[1]
    assert called_kwargs["file_id"] == "provided_cover_id"


@pytest.mark.parametrize(
    "today, expected",
    [
        ("2026-06-15", "2026-06-16"),  # Monday -> the coming Tuesday
        ("2026-06-16", "2026-06-16"),  # Tuesday -> the same day
        ("2026-06-17", "2026-06-23"),  # Wednesday -> the following Tuesday
        ("2026-06-21", "2026-06-23"),  # Sunday -> the following Tuesday
    ],
)
def test_next_tuesday(today, expected):
    """_next_tuesday returns the upcoming Tuesday, or today if today is Tuesday."""
    result = cover._next_tuesday(arrow.get(today))
    assert result.format("YYYY-MM-DD") == expected


@patch("generator.common.gdrive.GoogleDriveClient.download_file")
@patch("generator.worker.cover.CoverGenerator._apply_template_replacements")
@patch("generator.worker.cover.arrow.now")
def test_generate_cover_templates_date_and_next_tuesday(
    mock_now, mock_apply_replacements, mock_download_file
):
    """The forward replacement maps both {{DATE}} and {{NEXT_TUESDAY}}."""
    # Monday 2026-06-15; the coming Tuesday is 2026-06-16.
    mock_now.return_value = arrow.get("2026-06-15")
    mock_apply_replacements.return_value = {"{{DATE}}": 1, "{{NEXT_TUESDAY}}": 1}
    mock_download_file.return_value = b"fake-pdf-content"
    mock_config = config.Cover(file_id="cover123")

    generator = cover.CoverGenerator(
        Mock(spec=cover.GoogleDriveClient),
        Mock(),
        mock_config,
        enable_templating=True,
    )
    with patch("fitz.open"):
        generator.generate_cover("cover123")

    forward_map = mock_apply_replacements.call_args_list[0].args[1]
    assert forward_map == {
        "{{DATE}}": "15th June 2026",
        "{{NEXT_TUESDAY}}": "16th June 2026",
    }


def test_apply_template_replacements_returns_counts():
    """Returns per-placeholder occurrence counts from the batchUpdate replies."""
    response_body = json.dumps(
        {
            "replies": [
                {"replaceAllText": {"occurrencesChanged": 2}},
                {"replaceAllText": {}},  # placeholder not present in the doc
            ]
        }
    )
    docs_http = HttpMockSequence([({"status": "200"}, response_body)])
    docs = build("docs", "v1", http=docs_http)
    generator = cover.CoverGenerator(
        gdrive_client=Mock(spec=cover.GoogleDriveClient),
        docs_service=docs,
        cover_config=config.Cover(file_id="doc123"),
    )

    counts = generator._apply_template_replacements(
        "doc123", {"{{DATE}}": "a", "{{NEXT_TUESDAY}}": "b"}
    )

    assert counts == {"{{DATE}}": 2, "{{NEXT_TUESDAY}}": 0}


def test_apply_template_replacements_permission_error_returns_empty():
    """A failed update returns an empty mapping so nothing is reverted."""
    docs_http = HttpMockSequence([({"status": "403"}, "Permission denied")])
    docs = build("docs", "v1", http=docs_http)
    generator = cover.CoverGenerator(
        gdrive_client=Mock(spec=cover.GoogleDriveClient),
        docs_service=docs,
        cover_config=config.Cover(file_id="doc123"),
    )

    counts = generator._apply_template_replacements("doc123", {"{{DATE}}": "value"})

    assert counts == {}
