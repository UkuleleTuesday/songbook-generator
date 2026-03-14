"""Tests for editions module."""

import pytest
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


def test_scan_drive_editions_returns_valid_editions(mocker):
    """Valid edition folders with .songbook.yaml are returned as (folder_id, Edition) tuples."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock listing child folders
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        # First call: list child folders in source folder
        {"files": [{"id": "edition_folder_1", "name": "Edition 1"}]},
        # Second call: check for .songbook.yaml in edition_folder_1
        {"files": [{"id": "yaml_file_1"}]},
    ]

    mock_client.download_raw_bytes.return_value = _VALID_YAML

    # Mock settings to have source folders
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert len(result) == 1
    folder_id, edition = result[0]
    assert folder_id == "edition_folder_1"
    assert edition.id == "drive-edition"
    assert edition.title == "Drive Edition"


def test_scan_drive_editions_skips_invalid_yaml(mocker):
    """Folders with unparseable YAML are skipped with a warning."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock listing child folders and finding YAML file
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_b", "name": "Bad Folder"}]},
        {"files": [{"id": "bad_yaml"}]},
    ]

    mock_client.download_raw_bytes.return_value = _INVALID_YAML

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert result == []


def test_scan_drive_editions_skips_invalid_schema(mocker):
    """Folders with YAML that doesn't conform to Edition schema are skipped."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock listing child folders and finding YAML file
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_c", "name": "Bad Schema Folder"}]},
        {"files": [{"id": "bad_schema_yaml"}]},
    ]

    mock_client.download_raw_bytes.return_value = _INVALID_SCHEMA_YAML

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert result == []


def test_scan_drive_editions_skips_folders_without_yaml(mocker):
    """Edition folders without .songbook.yaml file are skipped."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock listing child folders
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        # First call: list child folders in source folder
        {"files": [{"id": "no_yaml_folder", "name": "No YAML Folder"}]},
        # Second call: check for .songbook.yaml in no_yaml_folder - not found
        {"files": []},
    ]

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert result == []
    mock_client.download_raw_bytes.assert_not_called()


def test_scan_drive_editions_multiple_folders(mocker):
    """Processes multiple edition folders and skips invalid ones."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock listing child folders and checking for YAML
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        # List child folders
        {
            "files": [
                {"id": "folder_good", "name": "Good Folder"},
                {"id": "folder_bad", "name": "Bad Folder"},
            ]
        },
        # Check for YAML in folder_good
        {"files": [{"id": "good_yaml"}]},
        # Check for YAML in folder_bad - will error
        {"files": [{"id": "bad_yaml"}]},
    ]

    http_err = HttpError(resp=MagicMock(status=404), content=b"Not Found")
    mock_client.download_raw_bytes.side_effect = [_VALID_YAML, http_err]

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert len(result) == 1
    folder_id, edition = result[0]
    assert folder_id == "folder_good"


def test_scan_drive_editions_empty_drive(mocker):
    """Returns empty list when no edition folders exist in Drive."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock listing child folders - returns empty
    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert result == []
    mock_client.download_raw_bytes.assert_not_called()


def test_scan_drive_editions_requires_source_folders(mocker):
    """When GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS is unset, returns empty list."""
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=None)
        ),
    )
    mock_client = mocker.Mock()

    result = scan_drive_editions(mock_client)

    assert result == []
    mock_client.drive.files.assert_not_called()


def test_scan_drive_editions_scopes_search_to_configured_folders(mocker):
    """When GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS is set, search is restricted to those folders."""
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["folder_x", "folder_y"])
        ),
    )
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Mock the Drive API calls - returns empty for both folders
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": []},  # folder_x
        {"files": []},  # folder_y
    ]

    result = scan_drive_editions(mock_client)

    assert result == []
    # Verify that list was called for each source folder
    assert mock_client.drive.files.return_value.list.call_count >= 2
