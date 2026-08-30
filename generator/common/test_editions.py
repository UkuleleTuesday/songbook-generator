"""Tests for editions module."""

import pytest
from googleapiclient.errors import HttpError
from unittest.mock import MagicMock

from .editions import (
    _YAML_SEARCH_BATCH_SIZE,
    _find_yaml_files_in_folders,
    _list_child_folders,
    scan_drive_editions,
    DriveEditionError,
    editions_config_prefix,
    resolve_editions,
    validate_config_ref,
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

    editions, errors = scan_drive_editions(mock_client)

    assert len(editions) == 1
    folder_id, edition = editions[0]
    assert folder_id == "edition_folder_1"
    assert edition.id == "drive-edition"
    assert edition.title == "Drive Edition"
    assert errors == []
    # Exactly 2 Drive API list calls (list folders + 1 batch YAML search)
    assert mock_client.drive.files.return_value.list.call_count == 2


def test_scan_drive_editions_invalid_yaml_returns_error(mocker):
    """Folders with unparseable YAML produce an error entry."""
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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert len(errors) == 1
    assert isinstance(errors[0], DriveEditionError)
    assert errors[0].folder_id == "folder_b"
    assert "parse" in errors[0].error.lower() or "yaml" in errors[0].error.lower()


def test_scan_drive_editions_invalid_schema_returns_error(mocker):
    """Folders with YAML that doesn't conform to Edition schema produce an error entry."""
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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert len(errors) == 1
    assert errors[0].folder_id == "folder_c"
    assert "schema" in errors[0].error.lower() or "edition" in errors[0].error.lower()


def test_scan_drive_editions_download_error_returns_error(mocker):
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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert len(errors) == 1
    assert errors[0].folder_id == "folder_d"
    assert "download" in errors[0].error.lower()


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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert errors == []
    mock_client.download_raw_bytes.assert_not_called()


def test_scan_drive_editions_multiple_folders(mocker):
    """Processes multiple edition folders; download errors go into the error list."""
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

    editions, errors = scan_drive_editions(mock_client)

    assert len(editions) == 1
    folder_id, edition = editions[0]
    assert folder_id == "folder_good"
    assert len(errors) == 1
    assert errors[0].folder_id == "folder_bad"
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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert errors == []
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

    editions, errors = scan_drive_editions(mock_client)

    assert len(editions) == 2
    folder_ids = {r[0] for r in editions}
    assert folder_ids == {"folder_p1", "folder_p2"}
    assert errors == []


def test_scan_drive_editions_empty_drive(mocker):
    """Returns empty lists when no edition folders exist in Drive."""
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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert errors == []
    mock_client.download_raw_bytes.assert_not_called()


def test_scan_drive_editions_requires_source_folders(mocker):
    """When GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS is unset, returns empty lists."""
    mocker.patch(
        "generator.common.editions.config.get_settings",
        return_value=mocker.Mock(songbook_editions=mocker.Mock(folder_ids=None)),
    )
    mock_client = mocker.Mock()

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert errors == []
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

    editions, errors = scan_drive_editions(mock_client)

    assert editions == []
    assert errors == []
    # One list call per configured source folder
    assert mock_client.drive.files.return_value.list.call_count == 2


# ---------------------------------------------------------------------------
# GCS-published config resolution tests
# ---------------------------------------------------------------------------


def _edition_yaml(eid):
    return f"id: {eid}\ntitle: {eid}\ndescription: {eid} edition\n".encode("utf-8")


def _mock_gcs(mocker, files=None, error=None):
    """Patch the storage client; list_blobs yields mock blobs for *files*.

    *files* maps blob name -> content bytes. *error* makes list_blobs raise.
    """
    mock_client = MagicMock()
    if error is not None:
        mock_client.list_blobs.side_effect = error
    else:
        blobs = []
        for name, content in (files or {}).items():
            blob = MagicMock()
            blob.name = name
            blob.download_as_bytes.return_value = content
            blobs.append(blob)
        mock_client.list_blobs.return_value = blobs
    mocker.patch(
        "generator.common.editions._get_storage_client", return_value=mock_client
    )
    return mock_client


def _mock_baked_settings(mocker, edition_ids):
    settings = MagicMock()
    settings.editions = [MagicMock(id=eid) for eid in edition_ids]
    mocker.patch("generator.common.editions.config.get_settings", return_value=settings)
    return settings


class TestValidateConfigRef:
    def test_accepts_main_and_pr_refs(self):
        assert validate_config_ref("main") == "main"
        assert validate_config_ref("pr-123") == "pr-123"

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            None,
            "pr-",
            "pr-1x",
            "PR-1",
            "main2",
            "../../etc",
            "gs://evil/x",
            "pr-1234567",
        ],
    )
    def test_rejects_malformed_refs(self, ref):
        with pytest.raises(ValueError):
            validate_config_ref(ref)


def test_editions_config_prefix():
    assert editions_config_prefix("pr-7") == "config/pr-7/"
    assert editions_config_prefix("main") == "config/main/"


class TestResolveEditions:
    def test_bucket_unset_returns_baked_without_gcs_call(self, mocker, monkeypatch):
        monkeypatch.delenv("EDITIONS_CONFIG_BUCKET", raising=False)
        settings = _mock_baked_settings(mocker, ["baked"])
        gcs = _mock_gcs(mocker, {"config/main/gcs.yaml": _edition_yaml("gcs")})

        editions, source = resolve_editions()

        assert source == "baked"
        assert editions == settings.editions
        gcs.list_blobs.assert_not_called()

    def test_gcs_set_replaces_baked_set_entirely(self, mocker, monkeypatch):
        """Whole-set replacement: a baked-only edition must not survive."""
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        _mock_baked_settings(mocker, ["baked-only", "shared", "extra"])
        _mock_gcs(
            mocker,
            {
                "config/main/shared.yaml": _edition_yaml("shared"),
                "config/main/a-new-one.yaml": _edition_yaml("new-one"),
            },
        )

        editions, source = resolve_editions()

        assert source == "gcs:main"
        # Sorted by blob name, matching the baked loader's sorted(os.listdir)
        assert [e.id for e in editions] == ["new-one", "shared"]

    def test_non_yaml_blobs_are_ignored(self, mocker, monkeypatch):
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        _mock_baked_settings(mocker, ["baked"])
        _mock_gcs(
            mocker,
            {
                "config/main/current.yaml": _edition_yaml("current"),
                "config/main/README.md": b"not an edition",
            },
        )

        editions, source = resolve_editions()

        assert source == "gcs:main"
        assert [e.id for e in editions] == ["current"]

    def test_default_ref_falls_back_to_baked_on_gcs_failure(self, mocker, monkeypatch):
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        settings = _mock_baked_settings(mocker, ["baked"])
        _mock_gcs(mocker, error=RuntimeError("gcs unavailable"))

        editions, source = resolve_editions()

        assert source == "baked"
        assert editions == settings.editions

    def test_empty_prefix_falls_back_to_baked(self, mocker, monkeypatch):
        """No published config set (e.g. before the first publish) means baked."""
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        settings = _mock_baked_settings(mocker, ["baked"])
        _mock_gcs(mocker, files={})

        editions, source = resolve_editions()

        assert source == "baked"
        assert editions == settings.editions

    def test_invalid_yaml_falls_back_to_baked(self, mocker, monkeypatch):
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        settings = _mock_baked_settings(mocker, ["baked"])
        _mock_gcs(mocker, {"config/main/bad.yaml": _INVALID_YAML})

        editions, source = resolve_editions()

        assert source == "baked"
        assert editions == settings.editions

    def test_explicit_ref_loads_pr_set(self, mocker, monkeypatch):
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        _mock_baked_settings(mocker, ["baked"])
        gcs = _mock_gcs(mocker, {"config/pr-42/x.yaml": _edition_yaml("pr-edition")})

        editions, source = resolve_editions("pr-42")

        assert source == "gcs:pr-42"
        assert [e.id for e in editions] == ["pr-edition"]
        gcs.list_blobs.assert_called_once_with("test-bucket", prefix="config/pr-42/")

    def test_explicit_ref_gcs_failure_raises(self, mocker, monkeypatch):
        """An explicitly requested config must never silently fall back."""
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        _mock_baked_settings(mocker, ["baked"])
        _mock_gcs(mocker, error=RuntimeError("gcs unavailable"))

        with pytest.raises(ValueError, match="pr-42"):
            resolve_editions("pr-42")

    def test_explicit_ref_empty_prefix_raises(self, mocker, monkeypatch):
        """A ref whose config set was never published fails the job."""
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        _mock_baked_settings(mocker, ["baked"])
        _mock_gcs(mocker, files={})

        with pytest.raises(ValueError, match="pr-42"):
            resolve_editions("pr-42")

    def test_explicit_ref_without_bucket_returns_baked(self, mocker, monkeypatch):
        """Mixed code+config PR envs have no bucket; baked config matches the PR."""
        monkeypatch.delenv("EDITIONS_CONFIG_BUCKET", raising=False)
        settings = _mock_baked_settings(mocker, ["baked"])
        gcs = _mock_gcs(mocker, {"config/main/gcs.yaml": _edition_yaml("gcs")})

        editions, source = resolve_editions("pr-42")

        assert source == "baked"
        assert editions == settings.editions
        gcs.list_blobs.assert_not_called()

    def test_malformed_ref_raises_before_gcs(self, mocker, monkeypatch):
        monkeypatch.setenv("EDITIONS_CONFIG_BUCKET", "test-bucket")
        gcs = _mock_gcs(mocker, {"config/main/gcs.yaml": _edition_yaml("gcs")})

        with pytest.raises(ValueError):
            resolve_editions("gs://evil/x")
        gcs.list_blobs.assert_not_called()
