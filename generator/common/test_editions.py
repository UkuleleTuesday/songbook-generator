"""Tests for editions module."""

from googleapiclient.errors import HttpError
from unittest.mock import MagicMock

from .editions import scan_drive_editions

_VALID_YAML = b"""
id: drive-edition
title: Drive Edition
description: A drive-based edition
filters:
  - key: specialbooks
    operator: contains
    value: test
"""

_INVALID_YAML = b": this: is: not: valid: yaml: {"

_INVALID_SCHEMA_YAML = b"""
title: Missing required id field
description: Missing id
filters: []
"""


def _mock_settings(mocker, folder_ids):
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(songbook_editions=mocker.Mock(folder_ids=folder_ids)),
    )


def test_scan_drive_editions_returns_valid_editions(mocker):
    """Valid .songbook.yaml files are returned as (folder_id, Edition) tuples."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Single ancestors query returns one YAML file
    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "yaml_file_1", "parents": ["edition_folder_1"]}]
    }
    mock_client.download_raw_bytes.return_value = _VALID_YAML

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert len(result) == 1
    folder_id, edition = result[0]
    assert folder_id == "edition_folder_1"
    assert edition.id == "drive-edition"
    assert edition.title == "Drive Edition"


def test_scan_drive_editions_uses_ancestors_query(mocker):
    """The Drive API query uses 'in ancestors' to avoid O(n) per-folder probing."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    _mock_settings(mocker, ["source_folder_x"])

    scan_drive_editions(mock_client)

    # Verify the query contains the ancestors clause
    list_call = mock_client.drive.files.return_value.list.call_args
    query = list_call.kwargs["q"]
    assert "in ancestors" in query
    assert "source_folder_x" in query
    assert ".songbook.yaml" in query


def test_scan_drive_editions_skips_invalid_yaml(mocker):
    """Folders with unparseable YAML are skipped with a warning."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "bad_yaml_id", "parents": ["folder_b"]}]
    }
    mock_client.download_raw_bytes.return_value = _INVALID_YAML

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert result == []


def test_scan_drive_editions_skips_invalid_schema(mocker):
    """Folders with YAML that doesn't conform to Edition schema are skipped."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "bad_schema_yaml_id", "parents": ["folder_c"]}]
    }
    mock_client.download_raw_bytes.return_value = _INVALID_SCHEMA_YAML

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert result == []


def test_scan_drive_editions_empty_drive(mocker):
    """Returns empty list when no .songbook.yaml files exist under source folder."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert result == []
    mock_client.download_raw_bytes.assert_not_called()


def test_scan_drive_editions_multiple_yamls(mocker):
    """Multiple valid .songbook.yaml files in the same source folder are all returned."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "good_yaml", "parents": ["folder_good"]},
            {"id": "bad_yaml", "parents": ["folder_bad"]},
        ]
    }

    http_err = HttpError(resp=MagicMock(status=404), content=b"Not Found")
    mock_client.download_raw_bytes.side_effect = [_VALID_YAML, http_err]

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert len(result) == 1
    folder_id, edition = result[0]
    assert folder_id == "folder_good"


def test_scan_drive_editions_requires_source_folders(mocker):
    """When GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS is unset, returns empty list."""
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(songbook_editions=mocker.Mock(folder_ids=None)),
    )
    mock_client = mocker.Mock()

    result = scan_drive_editions(mock_client)

    assert result == []
    mock_client.drive.files.assert_not_called()


def test_scan_drive_editions_scopes_search_to_configured_folders(mocker):
    """Search is issued once per configured source folder."""
    _mock_settings(mocker, ["folder_x", "folder_y"])
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    result = scan_drive_editions(mock_client)

    assert result == []
    # Exactly one list() call per source folder (no per-subfolder probing)
    assert mock_client.drive.files.return_value.list.call_count == 2


def test_scan_drive_editions_handles_pagination(mocker):
    """Results spread across multiple pages are all collected."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Page 1 has one YAML, page 2 has another
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {
            "nextPageToken": "token_page2",
            "files": [{"id": "yaml_p1", "parents": ["folder_p1"]}],
        },
        {
            "files": [{"id": "yaml_p2", "parents": ["folder_p2"]}],
        },
    ]
    mock_client.download_raw_bytes.return_value = _VALID_YAML

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert len(result) == 2
    folder_ids = {fid for fid, _ in result}
    assert folder_ids == {"folder_p1", "folder_p2"}
    # Two list() calls: page 1 and page 2
    assert mock_client.drive.files.return_value.list.call_count == 2
    # Second call must include the page token
    second_call_kwargs = mock_client.drive.files.return_value.list.call_args_list[
        1
    ].kwargs
    assert second_call_kwargs.get("pageToken") == "token_page2"


def test_scan_drive_editions_single_api_call_per_source_folder(mocker):
    """Only one Drive API list() call is made per source folder (O(1) not O(n))."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Simulate 10 editions in a single source folder
    yaml_files = [{"id": f"yaml_{i}", "parents": [f"folder_{i}"]} for i in range(10)]
    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": yaml_files
    }
    mock_client.download_raw_bytes.return_value = _VALID_YAML

    _mock_settings(mocker, ["source_folder"])

    result = scan_drive_editions(mock_client)

    assert len(result) == 10
    # Exactly ONE list() call regardless of how many editions were found
    assert mock_client.drive.files.return_value.list.call_count == 1
