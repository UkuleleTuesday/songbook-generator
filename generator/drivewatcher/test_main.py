"""Tests for the refactored drivewatcher consumer module."""

import json
import os
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from generator.drivewatcher.main import (
    _fetch_changes,
    _filter_changes_by_folders,
    _get_watched_folders,
    _publish_changes,
    drivewatcher_main,
)


def _make_tracer():
    mock_span = Mock()
    mock_tracer = Mock()
    mock_tracer.start_as_current_span.return_value.__enter__ = Mock(
        return_value=mock_span
    )
    mock_tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)
    return mock_tracer, mock_span


# ---------------------------------------------------------------------------
# _get_watched_folders
# ---------------------------------------------------------------------------


def test_get_watched_folders_from_env():
    """Test getting watched folders from environment variable."""
    with patch.dict(os.environ, {"DRIVE_WATCHED_FOLDERS": "folder1,folder2,folder3"}):
        folders = _get_watched_folders()
        assert folders == ["folder1", "folder2", "folder3"]


def test_get_watched_folders_from_config(monkeypatch):
    """Test getting watched folders from config when env var not set."""
    monkeypatch.delenv("DRIVE_WATCHED_FOLDERS", raising=False)

    mock_settings = Mock()
    mock_settings.song_sheets.folder_ids = [
        "config_folder1",
        "config_folder2",
    ]
    with patch(
        "generator.drivewatcher.main.get_settings",
        return_value=mock_settings,
    ):
        folders = _get_watched_folders()
        assert folders == ["config_folder1", "config_folder2"]


def test_get_watched_folders_strips_whitespace():
    """Test that folder IDs are stripped of whitespace."""
    with patch.dict(
        os.environ,
        {"DRIVE_WATCHED_FOLDERS": " folder1 , folder2 ,  "},
    ):
        folders = _get_watched_folders()
        assert folders == ["folder1", "folder2"]


# ---------------------------------------------------------------------------
# _fetch_changes
# ---------------------------------------------------------------------------


def test_fetch_changes_returns_new_start_token():
    """Test that the new start token is returned when all pages consumed."""
    mock_drive = Mock()
    mock_drive.changes.return_value.list.return_value.execute.return_value = {
        "newStartPageToken": "new-tok",
        "changes": [{"changeType": "file", "fileId": "f1"}],
    }
    services = {"drive": mock_drive}

    changes, token = _fetch_changes(services, "old-tok")

    assert token == "new-tok"
    assert len(changes) == 1
    assert changes[0]["fileId"] == "f1"


def test_fetch_changes_paginates():
    """Test that multiple pages are collected before the final token."""
    page1 = {
        "nextPageToken": "page2-tok",
        "changes": [{"changeType": "file", "fileId": "f1"}],
    }
    page2 = {
        "newStartPageToken": "final-tok",
        "changes": [{"changeType": "file", "fileId": "f2"}],
    }

    mock_list = Mock()
    mock_list.execute.side_effect = [page1, page2]
    mock_drive = Mock()
    mock_drive.changes.return_value.list.return_value = mock_list
    services = {"drive": mock_drive}

    changes, token = _fetch_changes(services, "start-tok")

    assert token == "final-tok"
    assert len(changes) == 2
    assert changes[0]["fileId"] == "f1"
    assert changes[1]["fileId"] == "f2"


def test_fetch_changes_no_new_token_falls_back():
    """Test that the original token is returned if API returns no new token."""
    mock_drive = Mock()
    mock_drive.changes.return_value.list.return_value.execute.return_value = {
        "changes": []
    }
    services = {"drive": mock_drive}

    changes, token = _fetch_changes(services, "same-tok")

    assert token == "same-tok"
    assert changes == []


# ---------------------------------------------------------------------------
# _filter_changes_by_folders
# ---------------------------------------------------------------------------


def test_filter_changes_includes_matching_folder():
    """Test that changes in watched folders are kept."""
    changes = [
        {
            "changeType": "file",
            "fileId": "f1",
            "file": {
                "id": "f1",
                "name": "Song.pdf",
                "parents": ["watched-folder"],
                "trashed": False,
                "mimeType": "application/pdf",
                "properties": {"key": "val"},
            },
        }
    ]

    result = _filter_changes_by_folders(changes, ["watched-folder"])

    assert len(result) == 1
    assert result[0]["id"] == "f1"
    assert result[0]["name"] == "Song.pdf"
    assert result[0]["folder_id"] == "watched-folder"
    assert result[0]["mime_type"] == "application/pdf"
    assert result[0]["properties"] == {"key": "val"}
    assert result[0]["parents"] == ["watched-folder"]


def test_filter_changes_excludes_unrelated_folder():
    """Test that changes outside watched folders are dropped."""
    changes = [
        {
            "changeType": "file",
            "fileId": "f1",
            "file": {
                "id": "f1",
                "name": "Other.pdf",
                "parents": ["other-folder"],
                "trashed": False,
                "mimeType": "application/pdf",
                "properties": {},
            },
        }
    ]

    result = _filter_changes_by_folders(changes, ["watched-folder"])

    assert result == []


def test_filter_changes_excludes_trashed_files():
    """Test that trashed files are not included."""
    changes = [
        {
            "changeType": "file",
            "fileId": "f1",
            "file": {
                "id": "f1",
                "name": "Trashed.pdf",
                "parents": ["watched-folder"],
                "trashed": True,
                "mimeType": "application/pdf",
                "properties": {},
            },
        }
    ]

    result = _filter_changes_by_folders(changes, ["watched-folder"])

    assert result == []


def test_filter_changes_excludes_non_file_changes():
    """Test that drive-level (non-file) changes are skipped."""
    changes = [{"changeType": "drive", "driveId": "shared-drive"}]

    result = _filter_changes_by_folders(changes, ["watched-folder"])

    assert result == []


def test_filter_changes_excludes_files_with_no_data():
    """Test that changes with no file object are skipped."""
    changes = [{"changeType": "file", "fileId": "f1", "removed": True}]

    result = _filter_changes_by_folders(changes, ["watched-folder"])

    assert result == []


def test_filter_changes_multiple_files_mixed():
    """Test filtering a mix of matching and non-matching changes."""
    changes = [
        {
            "changeType": "file",
            "fileId": "f1",
            "file": {
                "id": "f1",
                "name": "Kept.pdf",
                "parents": ["watched-folder"],
                "trashed": False,
                "mimeType": "application/pdf",
                "properties": {},
            },
        },
        {
            "changeType": "file",
            "fileId": "f2",
            "file": {
                "id": "f2",
                "name": "Dropped.pdf",
                "parents": ["other-folder"],
                "trashed": False,
                "mimeType": "application/pdf",
                "properties": {},
            },
        },
    ]

    result = _filter_changes_by_folders(changes, ["watched-folder"])

    assert len(result) == 1
    assert result[0]["id"] == "f1"


# ---------------------------------------------------------------------------
# _publish_changes
# ---------------------------------------------------------------------------


def test_publish_changes():
    """Test publishing changes to Pub/Sub."""
    check_time = datetime(2024, 1, 1, 12, 0, 0)
    changed_files = [
        {"id": "f1", "name": "Test.pdf", "folder_id": "folder1"},
        {"id": "f2", "name": "Other.pdf", "folder_id": "folder1"},
    ]

    mock_future = Mock()
    mock_future.result.return_value = None
    mock_publisher = Mock()
    mock_publisher.publish.return_value = mock_future
    mock_tracer, _ = _make_tracer()

    services = {
        "tracer": mock_tracer,
        "publisher": mock_publisher,
        "topic_path": "projects/test/topics/drive-changes",
    }

    with patch(
        "generator.drivewatcher.main._get_watched_folders",
        return_value=["folder1"],
    ):
        _publish_changes(services, changed_files, check_time)

    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args

    assert call_args[0][0] == "projects/test/topics/drive-changes"
    message = json.loads(call_args[0][1].decode("utf-8"))
    assert message["check_time"] == check_time.isoformat()
    assert message["file_count"] == 2
    assert message["changed_files"] == changed_files
    assert message["folders_checked"] == ["folder1"]
    assert call_args[1]["source"] == "drivewatcher"
    assert call_args[1]["change_count"] == "2"


def test_publish_changes_empty_list():
    """Test that nothing is published when the changes list is empty."""
    services = {"tracer": Mock(), "publisher": Mock()}
    _publish_changes(services, [], datetime.now(timezone.utc))
    services["publisher"].publish.assert_not_called()


# ---------------------------------------------------------------------------
# drivewatcher_main integration
# ---------------------------------------------------------------------------


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
@patch("generator.drivewatcher.main.get_page_token")
@patch("generator.drivewatcher.main._fetch_changes")
@patch("generator.drivewatcher.main._filter_changes_by_folders")
@patch("generator.drivewatcher.main._publish_changes")
@patch("generator.drivewatcher.main.save_page_token")
def test_drivewatcher_main_with_changes(
    mock_save_token,
    mock_publish,
    mock_filter,
    mock_fetch,
    mock_get_token,
    mock_get_folders,
    mock_get_services,
):
    """Test drivewatcher_main end-to-end when changes are found."""
    mock_tracer, _ = _make_tracer()
    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_folders.return_value = ["folder1", "folder2"]
    mock_get_token.return_value = "current-tok"
    mock_fetch.return_value = (
        [{"changeType": "file", "fileId": "f1"}],
        "new-tok",
    )
    mock_filter.return_value = [{"id": "f1", "name": "Song.pdf"}]

    drivewatcher_main(Mock())

    mock_fetch.assert_called_once_with(mock_get_services.return_value, "current-tok")
    mock_publish.assert_called_once()
    mock_save_token.assert_called_once_with(mock_get_services.return_value, "new-tok")


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
def test_drivewatcher_main_no_folders(mock_get_folders, mock_get_services):
    """Test that drivewatcher_main exits early with no folders configured."""
    mock_tracer, mock_span = _make_tracer()
    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_folders.return_value = []

    drivewatcher_main(Mock())

    mock_span.set_attribute.assert_any_call("status", "failed_no_folders")


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
@patch("generator.drivewatcher.main.get_page_token")
def test_drivewatcher_main_no_page_token(
    mock_get_token, mock_get_folders, mock_get_services
):
    """Test that drivewatcher_main exits early when no page token exists."""
    mock_tracer, mock_span = _make_tracer()
    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_folders.return_value = ["folder1"]
    mock_get_token.return_value = None

    drivewatcher_main(Mock())

    mock_span.set_attribute.assert_any_call("status", "no_page_token")


@patch("generator.drivewatcher.main._get_services")
@patch("generator.drivewatcher.main._get_watched_folders")
@patch("generator.drivewatcher.main.get_page_token")
@patch("generator.drivewatcher.main._fetch_changes")
@patch("generator.drivewatcher.main._filter_changes_by_folders")
@patch("generator.drivewatcher.main._publish_changes")
@patch("generator.drivewatcher.main.save_page_token")
def test_drivewatcher_main_no_relevant_changes(
    mock_save_token,
    mock_publish,
    mock_filter,
    mock_fetch,
    mock_get_token,
    mock_get_folders,
    mock_get_services,
):
    """Test that publish is skipped when no files match watched folders."""
    mock_tracer, mock_span = _make_tracer()
    mock_get_services.return_value = {"tracer": mock_tracer}
    mock_get_folders.return_value = ["folder1"]
    mock_get_token.return_value = "current-tok"
    mock_fetch.return_value = ([], "new-tok")
    mock_filter.return_value = []

    drivewatcher_main(Mock())

    mock_publish.assert_not_called()
    mock_save_token.assert_called_once_with(mock_get_services.return_value, "new-tok")
    mock_span.set_attribute.assert_any_call("status", "no_relevant_changes")
