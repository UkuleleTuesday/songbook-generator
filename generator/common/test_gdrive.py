import pytest
from unittest.mock import Mock, patch
from .gdrive import GoogleDriveClient, _build_property_filters
from .config import GoogleDriveClientConfig


@pytest.fixture
def mock_drive_client():
    """Create a mock GoogleDriveClient."""
    cache = Mock()
    config = GoogleDriveClientConfig(api_retries=3)
    client = GoogleDriveClient(cache=cache, drive=Mock(), config=config)
    return client


@pytest.fixture
def mock_drive():
    """Create a mock Google Drive service object."""
    drive = Mock()
    return drive


def test_search_files_by_name(mock_drive_client):
    """Test searching for a file by name."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}],
        "nextPageToken": None,
    }

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.search_files_by_name("Song 1", ["folder123"])

    assert len(result) == 1
    assert result[0].id == "file1"

    expected_query = (
        "name contains 'Song 1' and ('folder123' in parents) and trashed = false"
    )
    mock_drive_client.drive.files.return_value.list.assert_called_once_with(
        q=expected_query,
        pageSize=10,
        fields="files(id,name,parents,properties,mimeType)",
    )
    mock_drive_client.drive.files.return_value.list.return_value.execute.assert_called_once_with(
        num_retries=3
    )


def test_query_drive_files_basic(mock_drive_client):
    """Test basic functionality with a small result set."""
    # Mock the API response
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}, {"id": "file2", "name": "Song 2"}],
        "nextPageToken": None,
    }

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.query_drive_files(["folder123"])

    assert len(result) == 2
    assert result[0].id == "file1"
    assert result[0].name == "Song 1"
    assert result[1].id == "file2"
    assert result[1].name == "Song 2"

    # Verify the API was called correctly
    mock_drive_client.drive.files.return_value.list.assert_called_once_with(
        q="('folder123' in parents) and trashed = false",
        pageSize=1000,
        fields="nextPageToken, files(id,name,parents,properties,mimeType)",
        orderBy="name_natural",
        pageToken=None,
    )
    mock_drive_client.drive.files.return_value.list.return_value.execute.assert_called_once_with(
        num_retries=3
    )


def test_query_drive_files_with_multiple_folders(mock_drive_client):
    """Test querying multiple source folders."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response
    mock_drive_client.query_drive_files(["folder1", "folder2"])
    expected_query = (
        "('folder1' in parents or 'folder2' in parents) and trashed = false"
    )
    mock_drive_client.drive.files.return_value.list.assert_called_once_with(
        q=expected_query,
        pageSize=1000,
        fields="nextPageToken, files(id,name,parents,properties,mimeType)",
        orderBy="name_natural",
        pageToken=None,
    )
    mock_drive_client.drive.files.return_value.list.return_value.execute.assert_called_once_with(
        num_retries=3
    )


def test_query_drive_files_pagination(mock_drive_client):
    """Test pagination handling with multiple pages."""
    # First page response
    first_response = {
        "files": [{"id": "file1", "name": "Song 1"}, {"id": "file2", "name": "Song 2"}],
        "nextPageToken": "token123",
    }

    # Second page response
    second_response = {
        "files": [{"id": "file3", "name": "Song 3"}, {"id": "file4", "name": "Song 4"}],
        "nextPageToken": None,
    }

    # Configure mock to return different responses for each call
    mock_drive_client.drive.files.return_value.list.return_value.execute.side_effect = [
        first_response,
        second_response,
    ]

    result = mock_drive_client.query_drive_files(["folder123"])

    assert len(result) == 4
    assert result[0].id == "file1"
    assert result[1].id == "file2"
    assert result[2].id == "file3"
    assert result[3].id == "file4"

    # Verify two API calls were made
    assert mock_drive_client.drive.files.return_value.list.call_count == 2
    assert (
        mock_drive_client.drive.files.return_value.list.return_value.execute.call_count
        == 2
    )

    # Check the calls were made with correct parameters
    calls = mock_drive_client.drive.files.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "token123"

    # Verify num_retries was passed to execute calls
    execute_calls = mock_drive_client.drive.files.return_value.list.return_value.execute.call_args_list
    assert execute_calls[0].kwargs["num_retries"] == 3
    assert execute_calls[1].kwargs["num_retries"] == 3


def test_query_drive_files_empty_result(mock_drive_client):
    """Test handling of empty results."""
    mock_response = {"files": [], "nextPageToken": None}

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.query_drive_files(["folder123"])

    assert len(result) == 0
    assert result == []


def test_query_drive_files_no_files_key(mock_drive_client):
    """Test handling when 'files' key is missing from response."""
    mock_response = {"nextPageToken": None}

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.query_drive_files(["folder123"])

    assert len(result) == 0
    assert result == []


@patch("generator.common.gdrive.click.echo")
def test_query_drive_files_logs_query(mock_echo, mock_drive_client):
    """Test that the function logs the query being executed."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}],
        "nextPageToken": None,
    }

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    mock_drive_client.query_drive_files(["folder123"])

    # Verify the query was logged
    mock_echo.assert_called_once_with(
        "Executing Drive API query: ('folder123' in parents) and trashed = false"
    )


def test_query_drive_files_with_property_filters(mock_drive_client):
    """Test property filtering functionality."""
    mock_response = {
        "files": [
            {"id": "file1", "name": "Song 1", "properties": {"artist": "Beatles"}}
        ],
        "nextPageToken": None,
    }

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    property_filters = {"artist": "Beatles", "difficulty": "easy"}
    result = mock_drive_client.query_drive_files(["folder123"], property_filters)

    assert len(result) == 1
    assert result[0].id == "file1"

    # Verify the API was called with property filters
    expected_query = (
        "('folder123' in parents) and trashed = false and "
        "properties has { key='artist' and value='Beatles' } and "
        "properties has { key='difficulty' and value='easy' }"
    )

    mock_drive_client.drive.files.return_value.list.assert_called_once_with(
        q=expected_query,
        pageSize=1000,
        fields="nextPageToken, files(id,name,parents,properties,mimeType)",
        orderBy="name_natural",
        pageToken=None,
    )
    mock_drive_client.drive.files.return_value.list.return_value.execute.assert_called_once_with(
        num_retries=3
    )


@patch("generator.common.gdrive.click.echo")
def test_query_drive_files_logs_property_filters(mock_echo, mock_drive_client):
    """Test that property filters are logged."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}],
        "nextPageToken": None,
    }

    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    property_filters = {"artist": "Beatles"}
    mock_drive_client.query_drive_files(["folder123"], property_filters)

    # Verify both the query and filters were logged
    assert mock_echo.call_count == 2
    calls = [call.args[0] for call in mock_echo.call_args_list]
    assert any("Executing Drive API query:" in call for call in calls)
    assert any(
        "Filtering by properties: {'artist': 'Beatles'}" in call for call in calls
    )


def test__build_property_filters():
    """Test the _build_property_filters function."""
    # Test with no filters
    assert _build_property_filters(None) == ""
    assert _build_property_filters({}) == ""

    # Test with single filter
    result = _build_property_filters({"artist": "Beatles"})
    expected = " and properties has { key='artist' and value='Beatles' }"
    assert result == expected

    # Test with multiple filters
    result = _build_property_filters({"artist": "Beatles", "difficulty": "easy"})
    # Since dict order may vary, check both possible orders
    expected1 = (
        " and properties has { key='artist' and value='Beatles' } and "
        "properties has { key='difficulty' and value='easy' }"
    )
    expected2 = (
        " and properties has { key='difficulty' and value='easy' } and "
        "properties has { key='artist' and value='Beatles' }"
    )
    assert result in [expected1, expected2]

    # Test escaping single quotes
    result = _build_property_filters({"song": "Don't Stop Me Now"})
    expected = " and properties has { key='song' and value='Don\\'t Stop Me Now' }"
    assert result == expected


def test_query_drive_files_with_client_filter_no_filter(mock_drive_client, mocker):
    """Test client-side filtering when no filter is provided."""
    mock_files = [Mock(properties={}), Mock(properties={})]
    mocker.patch.object(mock_drive_client, "query_drive_files", return_value=mock_files)

    result = mock_drive_client.query_drive_files_with_client_filter(["folder123"])

    assert result == mock_files
    mock_drive_client.query_drive_files.assert_called_once_with(["folder123"], None)


def test_query_drive_files_with_client_filter_with_filter(mock_drive_client, mocker):
    """Test client-side filtering with a filter applied."""
    mock_files = [
        Mock(properties={"difficulty": "easy"}),
        Mock(properties={"difficulty": "hard"}),
    ]
    mocker.patch.object(mock_drive_client, "query_drive_files", return_value=mock_files)

    client_filter = Mock()
    client_filter.matches.side_effect = [
        True,
        False,
    ]  # First song matches, second fails

    result = mock_drive_client.query_drive_files_with_client_filter(
        ["folder123"], client_filter
    )

    assert len(result) == 1
    assert result[0] == mock_files[0]
    mock_drive_client.query_drive_files.assert_called_once_with(["folder123"], None)
    assert client_filter.matches.call_count == 2


# ---------------------------------------------------------------------------
# list_folder_contents tests
# ---------------------------------------------------------------------------


def test_list_folder_contents_regular_files(mock_drive_client):
    """Regular (non-shortcut) files are returned as-is."""
    mock_response = {
        "files": [
            {"id": "file1", "name": "Song A.pdf", "mimeType": "application/pdf"},
            {
                "id": "file2",
                "name": "Song B.pdf",
                "mimeType": "application/vnd.google-apps.document",
            },
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.list_folder_contents("folder123")

    assert len(result) == 2
    assert result[0].id == "file1"
    assert result[0].name == "Song A.pdf"
    assert result[0].mimeType == "application/pdf"
    assert result[1].id == "file2"
    assert result[1].name == "Song B.pdf"

    # The query must exclude sub-folders
    called_query = mock_drive_client.drive.files.return_value.list.call_args.kwargs["q"]
    assert "'folder123' in parents" in called_query
    assert "trashed = false" in called_query
    assert "application/vnd.google-apps.folder" in called_query


def test_list_folder_contents_subfolders_excluded(mock_drive_client):
    """Sub-folders in the Drive folder are excluded from results."""
    # Drive won't return folders because the query already excludes them,
    # so the mock returns only non-folder items even though the folder
    # contained a subfolder.  What we're really verifying is that the API
    # query string contains the folder-exclusion clause.
    mock_response = {
        "files": [
            {"id": "file1", "name": "Song A.pdf", "mimeType": "application/pdf"},
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    mock_drive_client.list_folder_contents("folder123")

    called_query = mock_drive_client.drive.files.return_value.list.call_args.kwargs["q"]
    assert "mimeType != 'application/vnd.google-apps.folder'" in called_query


def test_list_folder_contents_shortcut_to_folder_skipped(mock_drive_client):
    """Shortcuts whose target is a folder are silently skipped."""
    from .gdrive import SHORTCUT_MIME_TYPE

    folder_mime = "application/vnd.google-apps.folder"
    mock_response = {
        "files": [
            {
                "id": "sc1",
                "name": "Sub-edition folder",
                "mimeType": SHORTCUT_MIME_TYPE,
                "shortcutDetails": {
                    "targetId": "subfolder_id",
                    "targetMimeType": folder_mime,
                },
            },
            {"id": "file2", "name": "Good Song.pdf", "mimeType": "application/pdf"},
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.list_folder_contents("folder123")

    assert len(result) == 1
    assert result[0].id == "file2"


def test_list_folder_contents_shortcut_resolved(mock_drive_client):
    """Shortcuts are resolved: target ID/mimeType used, shortcut name retained."""
    from .gdrive import SHORTCUT_MIME_TYPE

    mock_response = {
        "files": [
            {
                "id": "shortcut1",
                "name": "My Song Shortcut",
                "mimeType": SHORTCUT_MIME_TYPE,
                "shortcutDetails": {
                    "targetId": "target_file_id",
                    "targetMimeType": "application/pdf",
                },
            }
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.list_folder_contents("folder123")

    assert len(result) == 1
    file = result[0]
    # Uses the target file's ID
    assert file.id == "target_file_id"
    # Retains the shortcut display name
    assert file.name == "My Song Shortcut"
    # Uses the target file's MIME type
    assert file.mimeType == "application/pdf"


def test_list_folder_contents_shortcut_missing_target_skipped(
    mock_drive_client, capsys
):
    """Shortcuts without a targetId are skipped with a warning."""
    from .gdrive import SHORTCUT_MIME_TYPE

    mock_response = {
        "files": [
            {
                "id": "shortcut1",
                "name": "Broken Shortcut",
                "mimeType": SHORTCUT_MIME_TYPE,
                "shortcutDetails": {},  # no targetId
            },
            {"id": "file2", "name": "Good Song.pdf", "mimeType": "application/pdf"},
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.list_folder_contents("folder123")

    # Only the non-broken file should be returned
    assert len(result) == 1
    assert result[0].id == "file2"


def test_list_folder_contents_pagination(mock_drive_client):
    """list_folder_contents handles pagination correctly."""
    page1 = {
        "files": [{"id": "a", "name": "A.pdf", "mimeType": "application/pdf"}],
        "nextPageToken": "tok1",
    }
    page2 = {
        "files": [{"id": "b", "name": "B.pdf", "mimeType": "application/pdf"}],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.side_effect = [
        page1,
        page2,
    ]

    result = mock_drive_client.list_folder_contents("folder123")

    assert len(result) == 2
    assert result[0].id == "a"
    assert result[1].id == "b"
    calls = mock_drive_client.drive.files.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "tok1"


def test_find_file_in_folder_found(mock_drive_client):
    """find_file_in_folder returns a File when the file exists."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "yaml-id",
                "name": ".songbook.yaml",
                "mimeType": "text/x-yaml",
                "parents": ["folder123"],
                "properties": {},
            }
        ]
    }

    result = mock_drive_client.find_file_in_folder("folder123", ".songbook.yaml")

    assert result is not None
    assert result.id == "yaml-id"
    assert result.name == ".songbook.yaml"
    mock_drive_client.drive.files.return_value.list.assert_called_once_with(
        q="'folder123' in parents and name = '.songbook.yaml' and trashed = false",
        pageSize=1,
        fields="files(id,name,mimeType,parents,properties)",
    )


def test_find_file_in_folder_not_found(mock_drive_client):
    """find_file_in_folder returns None when the file does not exist."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    result = mock_drive_client.find_file_in_folder("folder123", ".songbook.yaml")

    assert result is None


def test_find_file_in_folder_escapes_quotes(mock_drive_client):
    """find_file_in_folder escapes single quotes in the filename."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    mock_drive_client.find_file_in_folder("folder123", "it's a test.yaml")

    call_kwargs = mock_drive_client.drive.files.return_value.list.call_args.kwargs
    assert "it\\'s a test.yaml" in call_kwargs["q"]


def test_download_raw_bytes(mock_drive_client):
    """download_raw_bytes fetches raw content from Drive."""
    from unittest.mock import patch, MagicMock

    expected_content = b"id: test\ntitle: Test\n"

    def fake_next_chunk(_):
        return None, True

    mock_request = MagicMock()
    mock_drive_client.drive.files.return_value.get_media.return_value = mock_request

    with patch("generator.common.gdrive.MediaIoBaseDownload") as mock_downloader_cls:
        mock_downloader = MagicMock()
        mock_downloader.next_chunk.return_value = (None, True)
        mock_downloader_cls.return_value = mock_downloader

        # Patch the buffer write via side_effect on the constructor
        def make_downloader(buf, req):
            buf.write(expected_content)
            return mock_downloader

        mock_downloader_cls.side_effect = make_downloader

        result = mock_drive_client.download_raw_bytes("file-id-123")

    assert result == expected_content
    mock_drive_client.drive.files.return_value.get_media.assert_called_once_with(
        fileId="file-id-123"
    )


# ---------------------------------------------------------------------------
# find_all_files_named tests
# ---------------------------------------------------------------------------


def test_find_all_files_named_returns_matching_files(mock_drive_client):
    """Returns all files whose name matches exactly."""
    mock_response = {
        "files": [
            {
                "id": "cfg1",
                "name": ".songbook.yaml",
                "mimeType": "text/plain",
                "parents": ["folder_a"],
                "properties": {},
            },
            {
                "id": "cfg2",
                "name": ".songbook.yaml",
                "mimeType": "text/plain",
                "parents": ["folder_b"],
                "properties": {},
            },
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.find_all_files_named(".songbook.yaml")

    assert len(result) == 2
    assert result[0].id == "cfg1"
    assert result[1].id == "cfg2"

    called_query = mock_drive_client.drive.files.return_value.list.call_args.kwargs["q"]
    assert "name = '.songbook.yaml'" in called_query
    assert "trashed = false" in called_query
    # No parent restriction when source_folders is omitted
    assert "in parents" not in called_query


def test_find_all_files_named_with_source_folders(mock_drive_client):
    """When source_folders is provided, the query restricts to those parents."""
    mock_response = {
        "files": [
            {
                "id": "cfg1",
                "name": ".songbook.yaml",
                "mimeType": "text/plain",
                "parents": ["folder_a"],
                "properties": {},
            }
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.find_all_files_named(
        ".songbook.yaml", source_folders=["folder_a", "folder_b"]
    )

    assert len(result) == 1
    called_query = mock_drive_client.drive.files.return_value.list.call_args.kwargs["q"]
    assert "'folder_a' in parents" in called_query
    assert "'folder_b' in parents" in called_query


def test_find_all_files_named_empty_result(mock_drive_client):
    """Returns an empty list when no files match."""
    mock_response = {"files": [], "nextPageToken": None}
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = mock_drive_client.find_all_files_named(".songbook.yaml")

    assert result == []


def test_find_all_files_named_pagination(mock_drive_client):
    """Collects results across multiple pages."""
    first_response = {
        "files": [
            {
                "id": "cfg1",
                "name": ".songbook.yaml",
                "parents": ["folder_a"],
                "properties": {},
            }
        ],
        "nextPageToken": "tok",
    }
    second_response = {
        "files": [
            {
                "id": "cfg2",
                "name": ".songbook.yaml",
                "parents": ["folder_b"],
                "properties": {},
            }
        ],
        "nextPageToken": None,
    }
    mock_drive_client.drive.files.return_value.list.return_value.execute.side_effect = [
        first_response,
        second_response,
    ]

    result = mock_drive_client.find_all_files_named(".songbook.yaml")

    assert len(result) == 2
    assert result[0].id == "cfg1"
    assert result[1].id == "cfg2"


@patch("generator.common.gdrive.click.echo")
def test_find_all_files_named_http_error_returns_partial(mock_echo, mock_drive_client):
    """On an HttpError the method returns whatever was collected so far."""
    from googleapiclient.errors import HttpError
    from unittest.mock import MagicMock

    http_err = HttpError(resp=MagicMock(status=403), content=b"Forbidden")
    mock_drive_client.drive.files.return_value.list.return_value.execute.side_effect = (
        http_err
    )

    result = mock_drive_client.find_all_files_named(".songbook.yaml")

    assert result == []
    mock_echo.assert_called_once()
    assert "403" in mock_echo.call_args[0][0]


# ---------------------------------------------------------------------------
# find_subfolder_by_name tests
# ---------------------------------------------------------------------------


@patch("generator.common.gdrive.click.echo")
def test_find_subfolder_by_name_exact_match(mock_echo, mock_drive_client):
    """Returns the folder ID when a subfolder with matching name exists."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "cover_folder_id", "name": "Cover"},
            {"id": "other_folder_id", "name": "Other"},
        ]
    }

    result = mock_drive_client.find_subfolder_by_name("parent_id", "Cover")

    assert result == "cover_folder_id"


@patch("generator.common.gdrive.click.echo")
def test_find_subfolder_by_name_case_insensitive(mock_echo, mock_drive_client):
    """Matching is case-insensitive (e.g. 'cover' finds 'Cover')."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "cover_folder_id", "name": "Cover"},
        ]
    }

    result = mock_drive_client.find_subfolder_by_name("parent_id", "cover")

    assert result == "cover_folder_id"


@patch("generator.common.gdrive.click.echo")
def test_find_subfolder_by_name_not_found_returns_none(mock_echo, mock_drive_client):
    """Returns None when no subfolder matches."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "other_id", "name": "Other"}]
    }

    result = mock_drive_client.find_subfolder_by_name("parent_id", "Cover")

    assert result is None


@patch("generator.common.gdrive.click.echo")
def test_find_subfolder_by_name_empty_folder_returns_none(mock_echo, mock_drive_client):
    """Returns None when the parent folder has no subfolders."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    result = mock_drive_client.find_subfolder_by_name("parent_id", "Cover")

    assert result is None


@patch("generator.common.gdrive.click.echo")
def test_find_subfolder_by_name_http_error_returns_none(mock_echo, mock_drive_client):
    """Returns None and echoes an error on HttpError."""
    from googleapiclient.errors import HttpError
    from unittest.mock import MagicMock

    http_err = HttpError(resp=MagicMock(status=403), content=b"Forbidden")
    mock_drive_client.drive.files.return_value.list.return_value.execute.side_effect = (
        http_err
    )

    result = mock_drive_client.find_subfolder_by_name("parent_id", "Cover")

    assert result is None
    mock_echo.assert_called_once()
    assert "403" in mock_echo.call_args[0][0]


@patch("generator.common.gdrive.click.echo")
def test_find_subfolder_by_name_uses_folder_mime_type(mock_echo, mock_drive_client):
    """The API query filters by folder MIME type."""
    mock_drive_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    mock_drive_client.find_subfolder_by_name("parent_id", "Cover")

    call_kwargs = mock_drive_client.drive.files.return_value.list.call_args[1]
    assert "application/vnd.google-apps.folder" in call_kwargs["q"]
    assert "parent_id" in call_kwargs["q"]


# ---------------------------------------------------------------------------
# create_folder tests
# ---------------------------------------------------------------------------


def test_create_folder_returns_folder_id(mock_drive_client):
    """create_folder calls the Drive API and returns the new folder ID."""
    mock_drive_client.drive.files.return_value.create.return_value.execute.return_value = {
        "id": "new_folder_id"
    }

    result = mock_drive_client.create_folder("My Folder", "parent_id_123")

    assert result == "new_folder_id"
    call_kwargs = mock_drive_client.drive.files.return_value.create.call_args[1]
    body = call_kwargs["body"]
    assert body["name"] == "My Folder"
    assert body["mimeType"] == "application/vnd.google-apps.folder"
    assert body["parents"] == ["parent_id_123"]
    assert call_kwargs["fields"] == "id"


def test_create_folder_uses_api_retries(mock_drive_client):
    """create_folder passes api_retries to the execute call."""
    mock_drive_client.drive.files.return_value.create.return_value.execute.return_value = {
        "id": "folder_id"
    }

    mock_drive_client.create_folder("Test", "parent")

    mock_drive_client.drive.files.return_value.create.return_value.execute.assert_called_once_with(
        num_retries=3
    )


# ---------------------------------------------------------------------------
# upload_file_bytes tests
# ---------------------------------------------------------------------------


def test_upload_file_bytes_returns_file_id(mock_drive_client):
    """upload_file_bytes uploads content and returns the new file ID."""
    mock_drive_client.drive.files.return_value.create.return_value.execute.return_value = {
        "id": "uploaded_file_id"
    }

    result = mock_drive_client.upload_file_bytes(
        ".songbook.yaml",
        b"id: test\ntitle: Test",
        "parent_folder_id",
        mime_type="application/x-yaml",
    )

    assert result == "uploaded_file_id"
    call_kwargs = mock_drive_client.drive.files.return_value.create.call_args[1]
    body = call_kwargs["body"]
    assert body["name"] == ".songbook.yaml"
    assert body["parents"] == ["parent_folder_id"]
    assert call_kwargs["fields"] == "id"


def test_upload_file_bytes_uses_api_retries(mock_drive_client):
    """upload_file_bytes passes api_retries to the execute call."""
    mock_drive_client.drive.files.return_value.create.return_value.execute.return_value = {
        "id": "file_id"
    }

    mock_drive_client.upload_file_bytes("file.txt", b"data", "parent")

    mock_drive_client.drive.files.return_value.create.return_value.execute.assert_called_once_with(
        num_retries=3
    )


# ---------------------------------------------------------------------------
# create_shortcut tests
# ---------------------------------------------------------------------------


def test_create_shortcut_returns_shortcut_id(mock_drive_client):
    """create_shortcut creates a Drive shortcut and returns its ID."""
    mock_drive_client.drive.files.return_value.create.return_value.execute.return_value = {
        "id": "shortcut_id_abc"
    }

    result = mock_drive_client.create_shortcut(
        "_cover", "target_file_id", "parent_folder_id"
    )

    assert result == "shortcut_id_abc"
    call_kwargs = mock_drive_client.drive.files.return_value.create.call_args[1]
    body = call_kwargs["body"]
    assert body["name"] == "_cover"
    assert body["mimeType"] == "application/vnd.google-apps.shortcut"
    assert body["parents"] == ["parent_folder_id"]
    assert body["shortcutDetails"]["targetId"] == "target_file_id"
    assert call_kwargs["fields"] == "id"


def test_create_shortcut_uses_api_retries(mock_drive_client):
    """create_shortcut passes api_retries to the execute call."""
    mock_drive_client.drive.files.return_value.create.return_value.execute.return_value = {
        "id": "shortcut_id"
    }

    mock_drive_client.create_shortcut("_cover", "target", "parent")

    mock_drive_client.drive.files.return_value.create.return_value.execute.assert_called_once_with(
        num_retries=3
    )
