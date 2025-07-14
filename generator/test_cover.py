import json
import pytest
from unittest.mock import Mock, patch, mock_open
import fitz
import cover


from googleapiclient.errors import HttpError
from googleapiclient.http import HttpMockSequence


@pytest.fixture(autouse=True)
def mock_fs():
    """Auto-used fixture to mock filesystem operations."""
    with patch("cover.os.makedirs"), patch("cover.open", mock_open()) as mock_file:
        yield mock_file


@pytest.fixture(autouse=True)
def mock_google_apis():
    """Auto-used fixture to mock Google API clients and authentication."""
    with patch("cover.get_credentials"), patch("cover.build") as mock_build:
        yield mock_build


@pytest.fixture(autouse=True)
def mock_time_and_config():
    """Auto-used fixture to mock time and config loading."""
    with patch("cover.arrow.now") as mock_now, patch(
        "cover.config.load_cover_config"
    ) as mock_load_config:
        mock_now.return_value.format.return_value = "1st January 2024"
        yield {"now": mock_now, "load_config": mock_load_config}


@pytest.fixture
def mock_fitz():
    """Fixture to mock PDF processing with fitz."""
    with patch("cover.fitz.open") as mock_fitz_open:
        yield mock_fitz_open


def setup_google_api_mocks(mock_google_apis, drive_http, docs_http, export_content=b""):
    """Helper to set up mock Google Drive and Docs services."""
    mock_drive = cover.build("drive", "v3", http=drive_http)
    mock_drive.files().export().execute.return_value = export_content
    mock_docs = cover.build("docs", "v1", http=docs_http)
    mock_google_apis.side_effect = lambda service, *args, **kwargs: {
        "drive": mock_drive,
        "docs": mock_docs,
    }[service]


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


def test_generate_cover_basic(mock_fs, mock_google_apis, mock_fitz):
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
            # Note: The export call is mocked directly, so its response is not in the sequence.
            ({"status": "200"}, ""),  # for the delete call
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )
    setup_google_api_mocks(
        mock_google_apis, drive_http, docs_http, export_content=pdf_content
    )

    mock_pdf = Mock()
    mock_fitz.return_value = mock_pdf
    result = cover.generate_cover(mock_cache_dir, cover_file_id)

    assert result == mock_pdf
    mock_fs().write.assert_called_once_with(pdf_content)


@patch("cover.click.echo")
def test_generate_cover_no_cover_configured(mock_echo, mock_time_and_config):
    """Test when no cover file is configured."""
    mock_time_and_config["load_config"].return_value = None
    result = cover.generate_cover("/tmp/cache")
    assert result is None
    mock_echo.assert_called_once_with(
        "No cover file ID configured. Skipping cover generation."
    )


def test_generate_cover_corrupted_pdf(
    mock_google_apis, mock_time_and_config, mock_fitz
):
    """Test handling of corrupted PDF file."""
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"
    mock_time_and_config["load_config"].return_value = cover_file_id
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
    setup_google_api_mocks(
        mock_google_apis, drive_http, docs_http, export_content=b"corrupted"
    )
    mock_fitz.side_effect = fitz.EmptyFileError("Empty file")

    with pytest.raises(
        cover.CoverGenerationException, match="Downloaded cover file is corrupted"
    ):
        cover.generate_cover(mock_cache_dir, cover_file_id)


def test_generate_cover_deletion_failure(
    mock_google_apis, mock_time_and_config, mock_fitz
):
    """Test handling when temporary file deletion fails."""
    mock_cache_dir = "/tmp/cache"
    cover_file_id = "cover123"
    mock_time_and_config["load_config"].return_value = cover_file_id
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
    setup_google_api_mocks(
        mock_google_apis, drive_http, docs_http, export_content=b"pdf content"
    )

    mock_fitz.return_value = Mock()
    with pytest.raises(cover.CoverGenerationException):
        cover.generate_cover(mock_cache_dir, cover_file_id)


def test_generate_cover_uses_provided_cover_id(
    mock_google_apis, mock_time_and_config, mock_fitz
):
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
            ({"status": "200"}, ""),
        ]
    )
    docs_http = HttpMockSequence(
        [({"status": "200"}, json.dumps({"replies": []}))]
    )
    setup_google_api_mocks(
        mock_google_apis, drive_http, docs_http, export_content=pdf_content
    )
    mock_fitz.return_value = Mock()

    cover.generate_cover(mock_cache_dir, provided_cover_id)

    mock_time_and_config["load_config"].assert_not_called()


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
