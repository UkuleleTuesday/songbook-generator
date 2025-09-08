import pytest
import ssl
from unittest.mock import Mock, patch
from .gdrive import GoogleDriveClient, _build_property_filters, _retry_on_ssl_error


@pytest.fixture
def mock_drive_client():
    """Create a mock GoogleDriveClient."""
    cache = Mock()
    client = GoogleDriveClient(cache=cache, drive=Mock())
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

    # Check the calls were made with correct parameters
    calls = mock_drive_client.drive.files.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "token123"


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


def test_retry_decorator_success_after_ssl_errors():
    """Test that the retry decorator succeeds after SSL errors."""
    call_count = 0

    @_retry_on_ssl_error(max_retries=3, base_delay=0.01)
    def test_function():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ssl.SSLEOFError("EOF occurred in violation of protocol")
        return {"success": True}

    result = test_function()

    assert result == {"success": True}
    assert call_count == 3  # Should have been called 3 times


def test_retry_decorator_max_retries_exceeded():
    """Test that the retry decorator fails after max retries are exceeded."""
    call_count = 0

    @_retry_on_ssl_error(max_retries=2, base_delay=0.01)
    def test_function():
        nonlocal call_count
        call_count += 1
        raise ssl.SSLEOFError("EOF occurred in violation of protocol")

    with pytest.raises(ssl.SSLEOFError):
        test_function()

    assert call_count == 3  # Should have been called 3 times (initial + 2 retries)


def test_retry_decorator_non_ssl_error():
    """Test that the retry decorator doesn't retry non-SSL errors."""
    call_count = 0

    @_retry_on_ssl_error(max_retries=3, base_delay=0.01)
    def test_function():
        nonlocal call_count
        call_count += 1
        raise ValueError("Not an SSL error")

    with pytest.raises(ValueError):
        test_function()

    assert call_count == 1  # Should have been called only once


def test_gdrive_client_ssl_retry_integration(mock_drive_client):
    """Test that GoogleDriveClient properly retries on SSL errors."""
    call_count = 0

    def mock_execute():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ssl.SSLEOFError("EOF occurred in violation of protocol")
        return {
            "files": [
                {
                    "id": "test_id",
                    "name": "test_file.pdf",
                    "parents": ["folder_id"],
                    "properties": {},
                    "mimeType": "application/pdf",
                }
            ]
        }

    # Mock the execute method of the request object
    mock_request = Mock()
    mock_request.execute = mock_execute
    mock_drive_client.drive.files.return_value.list.return_value = mock_request

    # This should succeed after retries
    result = mock_drive_client.query_drive_files(["folder_id"])

    assert len(result) == 1
    assert result[0].name == "test_file.pdf"
    assert call_count == 3  # Should have retried twice
