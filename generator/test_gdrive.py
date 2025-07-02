import pytest
from unittest.mock import Mock, patch
from gdrive import query_drive_files, build_property_filters


@pytest.fixture
def mock_drive():
    """Create a mock Google Drive service object."""
    drive = Mock()
    return drive


def test_query_drive_files_basic(mock_drive):
    """Test basic functionality with a small result set."""
    # Mock the API response
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}, {"id": "file2", "name": "Song 2"}],
        "nextPageToken": None,
    }

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = query_drive_files(mock_drive, "folder123", None)

    assert len(result) == 2
    assert result[0]["id"] == "file1"
    assert result[0]["name"] == "Song 1"
    assert result[1]["id"] == "file2"
    assert result[1]["name"] == "Song 2"

    # Verify the API was called correctly
    mock_drive.files.return_value.list.assert_called_once_with(
        q="'folder123' in parents and trashed = false",
        pageSize=1000,
        fields="nextPageToken, files(id,name,properties)",
        orderBy="name_natural",
        pageToken=None,
    )


def test_query_drive_files_with_limit(mock_drive):
    """Test that limit parameter is respected."""
    mock_response = {
        "files": [
            {"id": "file1", "name": "Song 1"},
            {"id": "file2", "name": "Song 2"},
            {"id": "file3", "name": "Song 3"},
        ],
        "nextPageToken": None,
    }

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = query_drive_files(mock_drive, "folder123", 2)

    assert len(result) == 2
    assert result[0]["id"] == "file1"
    assert result[1]["id"] == "file2"

    # Verify the API was called with the limit as pageSize
    mock_drive.files.return_value.list.assert_called_once_with(
        q="'folder123' in parents and trashed = false",
        pageSize=2,
        fields="nextPageToken, files(id,name,properties)",
        orderBy="name_natural",
        pageToken=None,
    )


def test_query_drive_files_pagination(mock_drive):
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
    mock_drive.files.return_value.list.return_value.execute.side_effect = [
        first_response,
        second_response,
    ]

    result = query_drive_files(mock_drive, "folder123", None)

    assert len(result) == 4
    assert result[0]["id"] == "file1"
    assert result[1]["id"] == "file2"
    assert result[2]["id"] == "file3"
    assert result[3]["id"] == "file4"

    # Verify two API calls were made
    assert mock_drive.files.return_value.list.call_count == 2

    # Check the calls were made with correct parameters
    calls = mock_drive.files.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "token123"


def test_query_drive_files_pagination_with_limit(mock_drive):
    """Test pagination stops early when limit is reached."""
    # First page response with more files than the limit
    first_response = {
        "files": [
            {"id": "file1", "name": "Song 1"},
            {"id": "file2", "name": "Song 2"},
            {"id": "file3", "name": "Song 3"},
        ],
        "nextPageToken": "token123",
    }

    mock_drive.files.return_value.list.return_value.execute.return_value = (
        first_response
    )

    result = query_drive_files(mock_drive, "folder123", 2)

    # Should only return 2 files even though 3 were available
    assert len(result) == 2
    assert result[0]["id"] == "file1"
    assert result[1]["id"] == "file2"

    # Should only make one API call since limit was reached
    assert mock_drive.files.return_value.list.call_count == 1


def test_query_drive_files_empty_result(mock_drive):
    """Test handling of empty results."""
    mock_response = {"files": [], "nextPageToken": None}

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = query_drive_files(mock_drive, "folder123", None)

    assert len(result) == 0
    assert result == []


def test_query_drive_files_no_files_key(mock_drive):
    """Test handling when 'files' key is missing from response."""
    mock_response = {"nextPageToken": None}

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    result = query_drive_files(mock_drive, "folder123", None)

    assert len(result) == 0
    assert result == []


@patch("gdrive.click.echo")
def test_query_drive_files_logs_query(mock_echo, mock_drive):
    """Test that the function logs the query being executed."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}],
        "nextPageToken": None,
    }

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    query_drive_files(mock_drive, "folder123", None)

    # Verify the query was logged
    mock_echo.assert_called_once_with(
        "Executing Drive API query: 'folder123' in parents and trashed = false"
    )


def test_query_drive_files_multiple_pages_with_exact_limit(mock_drive):
    """Test pagination when limit exactly matches total available files."""
    # First page
    first_response = {
        "files": [{"id": "file1", "name": "Song 1"}, {"id": "file2", "name": "Song 2"}],
        "nextPageToken": "token123",
    }

    # Second page
    second_response = {
        "files": [{"id": "file3", "name": "Song 3"}],
        "nextPageToken": None,
    }

    mock_drive.files.return_value.list.return_value.execute.side_effect = [
        first_response,
        second_response,
    ]

    result = query_drive_files(mock_drive, "folder123", 3)

    assert len(result) == 3
    assert result[0]["id"] == "file1"
    assert result[1]["id"] == "file2"
    assert result[2]["id"] == "file3"

    # Should make two API calls to get all files
    assert mock_drive.files.return_value.list.call_count == 2


def test_query_drive_files_with_property_filters(mock_drive):
    """Test property filtering functionality."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1", "properties": {"artist": "Beatles"}}],
        "nextPageToken": None,
    }

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    property_filters = {"artist": "Beatles", "difficulty": "easy"}
    result = query_drive_files(mock_drive, "folder123", None, property_filters)

    assert len(result) == 1
    assert result[0]["id"] == "file1"

    # Verify the API was called with property filters
    expected_query = ("'folder123' in parents and trashed = false and "
                     "properties has { key='artist' and value='Beatles' } and "
                     "properties has { key='difficulty' and value='easy' }")
    
    mock_drive.files.return_value.list.assert_called_once_with(
        q=expected_query,
        pageSize=1000,
        fields="nextPageToken, files(id,name,properties)",
        orderBy="name_natural",
        pageToken=None,
    )


@patch("gdrive.click.echo")
def test_query_drive_files_logs_property_filters(mock_echo, mock_drive):
    """Test that property filters are logged."""
    mock_response = {
        "files": [{"id": "file1", "name": "Song 1"}],
        "nextPageToken": None,
    }

    mock_drive.files.return_value.list.return_value.execute.return_value = mock_response

    property_filters = {"artist": "Beatles"}
    query_drive_files(mock_drive, "folder123", None, property_filters)

    # Verify both the query and filters were logged
    assert mock_echo.call_count == 2
    calls = [call.args[0] for call in mock_echo.call_args_list]
    assert any("Executing Drive API query:" in call for call in calls)
    assert any("Filtering by properties: {'artist': 'Beatles'}" in call for call in calls)


def test_build_property_filters():
    """Test the build_property_filters function."""
    # Test with no filters
    assert build_property_filters(None) == ""
    assert build_property_filters({}) == ""
    
    # Test with single filter
    result = build_property_filters({"artist": "Beatles"})
    expected = " and properties has { key='artist' and value='Beatles' }"
    assert result == expected
    
    # Test with multiple filters
    result = build_property_filters({"artist": "Beatles", "difficulty": "easy"})
    # Since dict order may vary, check both possible orders
    expected1 = (" and properties has { key='artist' and value='Beatles' } and "
                "properties has { key='difficulty' and value='easy' }")
    expected2 = (" and properties has { key='difficulty' and value='easy' } and "
                "properties has { key='artist' and value='Beatles' }")
    assert result in [expected1, expected2]
    
    # Test escaping single quotes
    result = build_property_filters({"song": "Don't Stop Me Now"})
    expected = " and properties has { key='song' and value='Don\\'t Stop Me Now' }"
    assert result == expected
