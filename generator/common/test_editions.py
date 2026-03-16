"""Tests for editions module."""

from googleapiclient.errors import HttpError
from unittest.mock import MagicMock

from .editions import (
    _YAML_SEARCH_BATCH_SIZE,
    _find_yaml_files_in_folders,
    _list_child_folders,
    scan_drive_editions,
    scan_drive_editions_full,
    DriveEditionError,
)

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


# ---------------------------------------------------------------------------
# _list_child_folders unit tests
# ---------------------------------------------------------------------------


def test_list_child_folders_returns_all_pages(mocker):
    """Pagination is handled so folders beyond the first page are included."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        # Page 1 – includes nextPageToken
        {
            "files": [{"id": "f1", "name": "Folder 1"}],
            "nextPageToken": "token_page2",
        },
        # Page 2 – no nextPageToken
        {"files": [{"id": "f2", "name": "Folder 2"}]},
    ]

    result = _list_child_folders(mock_client, "source_folder")

    assert [f["id"] for f in result] == ["f1", "f2"]
    assert mock_client.drive.files.return_value.list.call_count == 2


def test_list_child_folders_empty_source(mocker):
    """Returns empty list when the source folder has no child folders."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    result = _list_child_folders(mock_client, "empty_source")

    assert result == []
    assert mock_client.drive.files.return_value.list.call_count == 1


# ---------------------------------------------------------------------------
# _find_yaml_files_in_folders unit tests
# ---------------------------------------------------------------------------


def test_find_yaml_files_maps_yaml_to_parent_folder(mocker):
    """Returns a dict mapping each folder_id to its .songbook.yaml file id."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "yaml1", "parents": ["folder_a"]}]
    }

    result = _find_yaml_files_in_folders(mock_client, ["folder_a", "folder_b"])

    assert result == {"folder_a": "yaml1"}
    # folder_b had no .songbook.yaml – not in result
    assert "folder_b" not in result


def test_find_yaml_files_batches_requests(mocker):
    """More than _YAML_SEARCH_BATCH_SIZE folders are split across multiple calls."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Create enough folders to require 2 batches
    folder_ids = [f"folder_{i}" for i in range(_YAML_SEARCH_BATCH_SIZE + 1)]

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    _find_yaml_files_in_folders(mock_client, folder_ids)

    # Should have made exactly 2 batch calls
    assert mock_client.drive.files.return_value.list.call_count == 2


def test_find_yaml_files_handles_pagination(mocker):
    """Results spanning multiple pages are all collected."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {
            "files": [{"id": "yaml1", "parents": ["folder_a"]}],
            "nextPageToken": "tok2",
        },
        {
            "files": [{"id": "yaml2", "parents": ["folder_b"]}],
        },
    ]

    result = _find_yaml_files_in_folders(mock_client, ["folder_a", "folder_b"])

    assert result == {"folder_a": "yaml1", "folder_b": "yaml2"}


def test_find_yaml_files_keeps_first_match_per_folder(mocker):
    """If a folder somehow contains multiple .songbook.yaml files, only the
    first one encountered is used."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "yaml_first", "parents": ["folder_a"]},
            {"id": "yaml_second", "parents": ["folder_a"]},
        ]
    }

    result = _find_yaml_files_in_folders(mock_client, ["folder_a"])

    assert result == {"folder_a": "yaml_first"}


# ---------------------------------------------------------------------------
# scan_drive_editions integration tests
# ---------------------------------------------------------------------------


def test_scan_drive_editions_returns_valid_editions(mocker):
    """Valid edition folders with .songbook.yaml are returned as (folder_id, Edition) tuples."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Call 1: list child folders (no nextPageToken)
    # Call 2: batch YAML search
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "edition_folder_1", "name": "Edition 1"}]},
        {"files": [{"id": "yaml_file_1", "parents": ["edition_folder_1"]}]},
    ]

    mock_client.download_raw_bytes.return_value = _VALID_YAML

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
    # Exactly 2 Drive API list calls (list folders + 1 batch YAML search)
    assert mock_client.drive.files.return_value.list.call_count == 2


def test_scan_drive_editions_skips_invalid_yaml(mocker):
    """Folders with unparseable YAML are skipped with a warning."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_b", "name": "Bad Folder"}]},
        {"files": [{"id": "bad_yaml", "parents": ["folder_b"]}]},
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

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_c", "name": "Bad Schema Folder"}]},
        {"files": [{"id": "bad_schema_yaml", "parents": ["folder_c"]}]},
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

    # Call 1: list child folders
    # Call 2: batch YAML search – returns nothing
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "no_yaml_folder", "name": "No YAML Folder"}]},
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
    """Processes multiple edition folders; download errors are skipped gracefully."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Call 1: list child folders (two folders)
    # Call 2: single batch YAML search returning both YAML files
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {
            "files": [
                {"id": "folder_good", "name": "Good Folder"},
                {"id": "folder_bad", "name": "Bad Folder"},
            ]
        },
        {
            "files": [
                {"id": "good_yaml", "parents": ["folder_good"]},
                {"id": "bad_yaml", "parents": ["folder_bad"]},
            ]
        },
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
    # Only 2 Drive API list calls (no per-folder calls)
    assert mock_client.drive.files.return_value.list.call_count == 2


def test_scan_drive_editions_batches_yaml_search(mocker):
    """When there are more than _YAML_SEARCH_BATCH_SIZE child folders the YAML
    search is split into multiple calls rather than one call per folder."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    # Build just over one batch worth of folders
    n_folders = _YAML_SEARCH_BATCH_SIZE + 5
    child_folders = [
        {"id": f"folder_{i}", "name": f"Folder {i}"} for i in range(n_folders)
    ]

    # Call 1: list child folders
    # Calls 2-3: two YAML batch searches (one full batch + one partial)
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": child_folders},  # list child folders
        {"files": []},  # batch 1 YAML search
        {"files": []},  # batch 2 YAML search
    ]

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert result == []
    # 1 list-folders call + 2 YAML batch calls
    assert mock_client.drive.files.return_value.list.call_count == 3


def test_scan_drive_editions_paginates_child_folders(mocker):
    """Child folders spanning multiple pages are all processed."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        # Page 1 of child folders
        {
            "files": [{"id": "folder_p1", "name": "Page1 Folder"}],
            "nextPageToken": "tok2",
        },
        # Page 2 of child folders
        {"files": [{"id": "folder_p2", "name": "Page2 Folder"}]},
        # Batch YAML search for both folders (one batch)
        {
            "files": [
                {"id": "yaml_p1", "parents": ["folder_p1"]},
                {"id": "yaml_p2", "parents": ["folder_p2"]},
            ]
        },
    ]

    mock_client.download_raw_bytes.return_value = _VALID_YAML

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    result = scan_drive_editions(mock_client)

    assert len(result) == 2
    folder_ids = {r[0] for r in result}
    assert folder_ids == {"folder_p1", "folder_p2"}


def test_scan_drive_editions_empty_drive(mocker):
    """Returns empty list when no edition folders exist in Drive."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

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
        return_value=mocker.Mock(songbook_editions=mocker.Mock(folder_ids=None)),
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

    # Both source folders have no child folders
    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": []},  # folder_x child-folder listing
        {"files": []},  # folder_y child-folder listing
    ]

    result = scan_drive_editions(mock_client)

    assert result == []
    # One list call per configured source folder
    assert mock_client.drive.files.return_value.list.call_count == 2


# ---------------------------------------------------------------------------
# scan_drive_editions_full tests
# ---------------------------------------------------------------------------


def test_scan_drive_editions_full_returns_valid_and_errors(mocker):
    """scan_drive_editions_full returns valid editions AND error entries."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {
            "files": [
                {"id": "folder_good", "name": "Good Folder"},
                {"id": "folder_bad", "name": "Bad Folder"},
            ]
        },
        {
            "files": [
                {"id": "good_yaml", "parents": ["folder_good"]},
                {"id": "bad_yaml", "parents": ["folder_bad"]},
            ]
        },
    ]

    mock_client.download_raw_bytes.side_effect = [_VALID_YAML, _INVALID_YAML]

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    editions, errors = scan_drive_editions_full(mock_client)

    assert len(editions) == 1
    folder_id, edition = editions[0]
    assert folder_id == "folder_good"
    assert edition.title == "Drive Edition"

    assert len(errors) == 1
    err = errors[0]
    assert isinstance(err, DriveEditionError)
    assert err.folder_id == "folder_bad"
    assert err.folder_name == "Bad Folder"
    assert "parse" in err.error.lower() or "yaml" in err.error.lower()


def test_scan_drive_editions_full_invalid_schema_returns_error(mocker):
    """.songbook.yaml with invalid schema is captured as an error entry."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_c", "name": "Bad Schema Folder"}]},
        {"files": [{"id": "bad_schema_yaml", "parents": ["folder_c"]}]},
    ]

    mock_client.download_raw_bytes.return_value = _INVALID_SCHEMA_YAML

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    editions, errors = scan_drive_editions_full(mock_client)

    assert editions == []
    assert len(errors) == 1
    err = errors[0]
    assert err.folder_id == "folder_c"
    assert err.folder_name == "Bad Schema Folder"
    assert "schema" in err.error.lower() or "edition" in err.error.lower()


def test_scan_drive_editions_full_download_error_returns_error(mocker):
    """HTTP error when downloading .songbook.yaml is captured as an error entry."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_d", "name": "Download Error Folder"}]},
        {"files": [{"id": "bad_download", "parents": ["folder_d"]}]},
    ]

    http_err = HttpError(resp=MagicMock(status=404), content=b"Not Found")
    mock_client.download_raw_bytes.side_effect = http_err

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    editions, errors = scan_drive_editions_full(mock_client)

    assert editions == []
    assert len(errors) == 1
    err = errors[0]
    assert err.folder_id == "folder_d"
    assert err.folder_name == "Download Error Folder"
    assert "download" in err.error.lower()


def test_scan_drive_editions_full_no_errors_when_all_valid(mocker):
    """scan_drive_editions_full returns empty error list when all editions valid."""
    mock_client = mocker.Mock()
    mock_client.config = mocker.Mock(api_retries=3)

    mock_client.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder_good", "name": "Good Folder"}]},
        {"files": [{"id": "good_yaml", "parents": ["folder_good"]}]},
    ]

    mock_client.download_raw_bytes.return_value = _VALID_YAML

    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(
            songbook_editions=mocker.Mock(folder_ids=["source_folder"])
        ),
    )

    editions, errors = scan_drive_editions_full(mock_client)

    assert len(editions) == 1
    assert errors == []


def test_scan_drive_editions_full_no_source_folders(mocker):
    """scan_drive_editions_full returns empty lists when no folders configured."""
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(songbook_editions=mocker.Mock(folder_ids=None)),
    )
    mock_client = mocker.Mock()

    editions, errors = scan_drive_editions_full(mock_client)

    assert editions == []
    assert errors == []
    mock_client.drive.files.assert_not_called()
