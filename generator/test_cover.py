import json
import pytest
from unittest.mock import Mock, patch, mock_open
import fitz
import cover


from googleapiclient.errors import HttpError
from googleapiclient.http import HttpMockSequence


@pytest.fixture
def mock_cover_dependencies():
    """A fixture to mock all external dependencies for cover generation."""
    with (
        patch("cover.os.makedirs") as mock_makedirs,
        patch("cover.open", mock_open()) as mock_file,
        patch("cover.fitz.open") as mock_fitz,
        patch("cover.get_credentials") as mock_get_credentials,
        patch("cover.build") as mock_build,
        patch("cover.arrow.now") as mock_now,
        patch("cover.config.load_cover_config") as mock_load_config,
    ):
        mock_now.return_value.format.return_value = "1st January 2024"
        yield {
            "makedirs": mock_makedirs,
            "file": mock_file,
            "fitz": mock_fitz,
            "get_credentials": mock_get_credentials,
            "build": mock_build,
            "now": mock_now,
            "load_config": mock_load_config,
        }


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


def test_generate_cover_basic(mock_cover_dependencies):
    """Test basic cover generation functionality."""
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"
    pdf_content = b"fake pdf content"

    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, pdf_content),
            ({"status": "200"}, ""),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )

    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_cover_dependencies["build"].side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]

    mock_pdf = Mock()
    mock_cover_dependencies["fitz"].return_value = mock_pdf

    result = cover.generate_cover(
        mock_cache_dir, cover_file_id, build_service=mock_cover_dependencies["build"]
    )

    assert result == mock_pdf
    mock_cover_dependencies["file"]().write.assert_called_once_with(pdf_content)


@patch("cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo, mock_cover_dependencies):
    """Test when no cover file is configured."""
    mock_cover_dependencies["load_config"].return_value = None
    mock_cache_dir = "/tmp/cache"

    with patch("cover.config.load_cover_config") as mock_load_config:
        mock_load_config.return_value = None
        result = cover.generate_cover(mock_cache_dir)

        assert result is None
        mock_echo.assert_called_once_with(
            "No cover file ID configured. Skipping cover generation."
        )


def test_generate_cover_corrupted_pdf(mock_cover_dependencies):
    """Test handling of corrupted PDF file."""
    pdf_content = b"corrupted pdf content"
    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, pdf_content),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"
    mock_cover_dependencies["load_config"].return_value = cover_file_id

    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_cover_dependencies["build"].side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_cover_dependencies["fitz"].side_effect = fitz.EmptyFileError("Empty file")

    with pytest.raises(
        cover.CoverGenerationException, match="Downloaded cover file is corrupted"
    ):
        cover.generate_cover(
            mock_cache_dir,
            cover_file_id,
            build_service=mock_cover_dependencies["build"],
        )


def test_generate_cover_deletion_failure(mock_cover_dependencies):
    """Test handling when temporary file deletion fails."""
    pdf_content = b"fake pdf content"
    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, pdf_content),
            (Mock(status=500), b"API Error"),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )

    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"
    mock_cover_dependencies["load_config"].return_value = cover_file_id

    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_cover_dependencies["build"].side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_pdf = Mock()
    mock_cover_dependencies["fitz"].return_value = mock_pdf

    with pytest.raises(cover.CoverGenerationException):
        cover.generate_cover(
            mock_cache_dir,
            cover_file_id,
            build_service=mock_cover_dependencies["build"],
        )


def test_generate_cover_uses_provided_cover_id(mock_cover_dependencies):
    """Test that provided cover_file_id takes precedence over config."""
    mock_cache_dir = "/tmp/cache"
    provided_cover_id = "provided_cover123"
    pdf_content = b"fake pdf content"

    drive_http = HttpMockSequence(
        [
            ({"status": "200"}, json.dumps({"id": "root_id"})),
            (
                {"status": "200"},
                json.dumps({"id": "temp_cover123", "name": "Copy of template"}),
            ),
            ({"status": "200"}, pdf_content),
            ({"status": "200"}, ""),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )

    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_cover_dependencies["build"].side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]
    mock_pdf = Mock()
    mock_cover_dependencies["fitz"].return_value = mock_pdf

    cover.generate_cover(
        mock_cache_dir,
        provided_cover_id,
        build_service=mock_cover_dependencies["build"],
    )

    # Config should not be loaded when cover_file_id is provided
    mock_cover_dependencies["load_config"].assert_not_called()


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
