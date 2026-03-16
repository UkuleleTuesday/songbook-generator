import pytest
import yaml as pyyaml
from click.testing import CliRunner
from googleapiclient.errors import HttpError
from unittest.mock import MagicMock

from ..cli import cli
from ..common.config import Edition


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# editions list tests
# ---------------------------------------------------------------------------

_EDITION_FILTERS = [{"key": "specialbooks", "operator": "contains", "value": "current"}]
_EDITION_DESCRIPTION = "Test edition"


def test_editions_list_shows_config_and_drive_editions(runner, mocker):
    """editions list shows both config and drive-detected editions."""
    config_edition = Edition(
        id="current",
        title="Current Songbook",
        description=_EDITION_DESCRIPTION,
        filters=_EDITION_FILTERS,
    )
    mocker.patch("generator.cli.editions.get_settings").return_value = mocker.Mock(
        editions=[config_edition],
        google_cloud=mocker.Mock(
            credentials={
                "songbook-generator": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        songbook_editions=mocker.Mock(folder_ids=[]),
    )
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    drive_edition = Edition(
        id="drive-ed",
        title="Drive Songbook",
        description=_EDITION_DESCRIPTION,
        filters=_EDITION_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.scan_drive_editions",
        return_value=[("folder_abc", drive_edition)],
    )

    result = runner.invoke(cli, ["editions", "list"])

    assert result.exit_code == 0
    assert "Config editions:" in result.output
    assert "[current] Current Songbook" in result.output
    assert "Drive editions:" in result.output
    assert "[folder_abc] Drive Songbook" in result.output


def test_editions_list_no_drive_editions(runner, mocker):
    """editions list reports when no drive editions are found."""
    config_edition = Edition(
        id="current",
        title="Current Songbook",
        description=_EDITION_DESCRIPTION,
        filters=_EDITION_FILTERS,
    )
    mocker.patch("generator.cli.editions.get_settings").return_value = mocker.Mock(
        editions=[config_edition],
        google_cloud=mocker.Mock(
            credentials={
                "songbook-generator": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        songbook_editions=mocker.Mock(folder_ids=[]),
    )
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch("generator.cli.editions.scan_drive_editions", return_value=[])

    result = runner.invoke(cli, ["editions", "list"])

    assert result.exit_code == 0
    assert "Config editions:" in result.output
    assert "No drive editions found." in result.output


def test_editions_list_drive_scan_http_error(runner, mocker):
    """editions list degrades gracefully when Drive scan raises HttpError."""
    config_edition = Edition(
        id="current",
        title="Current Songbook",
        description=_EDITION_DESCRIPTION,
        filters=_EDITION_FILTERS,
    )
    mocker.patch("generator.cli.editions.get_settings").return_value = mocker.Mock(
        editions=[config_edition],
        google_cloud=mocker.Mock(
            credentials={
                "songbook-generator": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        songbook_editions=mocker.Mock(folder_ids=[]),
    )
    mocker.patch(
        "generator.cli.editions.init_services",
        side_effect=HttpError(resp=MagicMock(status=403), content=b"Forbidden"),
    )

    result = runner.invoke(cli, ["editions", "list"])

    assert result.exit_code == 0
    assert "Config editions:" in result.output
    assert "Drive scan failed" in result.output


def test_editions_list_no_config_editions(runner, mocker):
    """editions list reports when no config editions exist."""
    mocker.patch("generator.cli.editions.get_settings").return_value = mocker.Mock(
        editions=[],
        google_cloud=mocker.Mock(
            credentials={
                "songbook-generator": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        songbook_editions=mocker.Mock(folder_ids=[]),
    )
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch("generator.cli.editions.scan_drive_editions", return_value=[])

    result = runner.invoke(cli, ["editions", "list"])

    assert result.exit_code == 0
    assert "No config editions found." in result.output


# ---------------------------------------------------------------------------
# editions convert tests
# ---------------------------------------------------------------------------

_CONVERT_FILTERS = [{"key": "specialbooks", "operator": "contains", "value": "test"}]
_CONVERT_DESCRIPTION = "A test edition"


def _make_convert_settings(mocker, edition, folder_ids=None):
    """Return a mock settings object for convert_edition tests."""
    return mocker.Mock(
        editions=[edition],
        songbook_editions=mocker.Mock(
            folder_ids=folder_ids if folder_ids is not None else ["editions_folder"]
        ),
        song_sheets=mocker.Mock(folder_ids=["song_sheets_folder_id"]),
    )


def test_convert_edition_success(runner, mocker):
    """editions convert creates a Drive folder and uploads .songbook.yaml."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mock_init = mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "new_folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_file_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Creating Drive folder 'Test Edition'" in result.output
    assert "Created folder (id=new_folder_id)" in result.output
    assert "Uploading .songbook.yaml" in result.output
    assert "Uploaded .songbook.yaml (id=yaml_file_id)" in result.output
    assert "Conversion complete." in result.output
    assert "new_folder_id" in result.output
    mock_instance.create_folder.assert_called_once_with(
        "Test Edition", "editions_folder"
    )
    mock_instance.upload_file_bytes.assert_called_once()
    call_args = mock_instance.upload_file_bytes.call_args
    assert call_args[0][0] == ".songbook.yaml"
    assert isinstance(call_args[0][1], bytes)
    assert call_args[0][2] == "new_folder_id"
    # Must not impersonate a service account principal
    _, init_kwargs = mock_init.call_args
    assert init_kwargs.get("target_principal") is None


def test_convert_edition_custom_folder_name(runner, mocker):
    """editions convert uses --folder-name when provided."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--folder-name",
            "My Custom Name",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    mock_instance.create_folder.assert_called_once_with(
        "My Custom Name", "editions_folder"
    )


def test_convert_edition_unknown_edition(runner, mocker):
    """editions convert aborts when the edition ID does not exist."""
    mocker.patch("generator.cli.editions.get_settings").return_value = mocker.Mock(
        editions=[],
        songbook_editions=mocker.Mock(folder_ids=[]),
    )

    result = runner.invoke(
        cli,
        ["editions", "convert", "nonexistent", "--target-folder", "folder"],
    )

    assert result.exit_code != 0
    assert "not found in config editions" in result.output


def test_convert_edition_no_target_folder_no_config(runner, mocker):
    """editions convert aborts when no --target-folder and no config folder."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition, folder_ids=[])

    result = runner.invoke(cli, ["editions", "convert", "test-ed"])

    assert result.exit_code != 0
    assert "GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS" in result.output


def test_convert_edition_no_target_folder_multiple_config(runner, mocker):
    """editions convert aborts when multiple config folders and no --target-folder."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(
        mocker, edition, folder_ids=["folder_a", "folder_b"]
    )

    result = runner.invoke(cli, ["editions", "convert", "test-ed"])

    assert result.exit_code != 0
    assert "Please specify --target-folder" in result.output


def test_convert_edition_uses_single_config_folder(runner, mocker):
    """editions convert auto-selects target when exactly one folder is configured."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition, folder_ids=["only_folder"])
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        ["editions", "convert", "test-ed", "--no-create-shortcuts"],
    )

    assert result.exit_code == 0, result.output
    mock_instance.create_folder.assert_called_once_with("Test Edition", "only_folder")


def test_convert_edition_creates_shortcuts(runner, mocker):
    """editions convert creates Cover/Preface/Postface/Songs subfolders with shortcuts."""
    from ..worker.models import File as DriveFile

    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
        cover_file_id="cover_id",
        preface_file_ids=["preface_id"],
        postface_file_ids=["post1_id", "post2_id"],
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    # edition folder + Cover + Preface + Postface + Songs subfolders
    mock_instance.create_folder.side_effect = [
        "edition_folder_id",
        "cover_sub_id",
        "preface_sub_id",
        "postface_sub_id",
        "songs_sub_id",
    ]
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mock_instance.create_shortcut.return_value = "shortcut_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)
    song_files = [
        DriveFile(id="song1_id", name="Song One"),
        DriveFile(id="song2_id", name="Song Two"),
    ]
    mocker.patch(
        "generator.cli.editions.collect_and_sort_files", return_value=song_files
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Creating component subfolders" in result.output

    # Five create_folder calls: edition + Cover + Preface + Postface + Songs
    assert mock_instance.create_folder.call_count == 5
    folder_names = [c[0][0] for c in mock_instance.create_folder.call_args_list]
    assert folder_names[0] == "Test Edition"
    assert "Cover" in folder_names
    assert "Preface" in folder_names
    assert "Postface" in folder_names
    assert "Songs" in folder_names

    # 6 shortcuts: cover, preface, postface_01, postface_02, Song One, Song Two
    assert mock_instance.create_shortcut.call_count == 6
    shortcut_args = [c[0] for c in mock_instance.create_shortcut.call_args_list]
    shortcut_names = [a[0] for a in shortcut_args]
    assert "cover" in shortcut_names
    assert "preface" in shortcut_names
    assert "postface_01" in shortcut_names
    assert "postface_02" in shortcut_names
    assert "Song One" in shortcut_names
    assert "Song Two" in shortcut_names


def test_convert_edition_yaml_has_use_folder_components(runner, mocker):
    """editions convert sets use_folder_components=true when shortcuts are created."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
        cover_file_id="cover_id",
        preface_file_ids=["preface_id"],
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    uploaded_content = {}

    def capture_upload(name, content, parent_id, mime_type="application/octet-stream"):
        uploaded_content["content"] = content
        return "yaml_id"

    mock_instance.upload_file_bytes.side_effect = capture_upload
    mock_instance.create_shortcut.return_value = "shortcut_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)
    mocker.patch("generator.cli.editions.collect_and_sort_files", return_value=[])

    result = runner.invoke(
        cli,
        ["editions", "convert", "test-ed", "--target-folder", "editions_folder"],
    )

    assert result.exit_code == 0, result.output
    assert "content" in uploaded_content
    parsed = pyyaml.safe_load(uploaded_content["content"].decode("utf-8"))
    # use_folder_components must be set when --create-shortcuts is on
    assert parsed.get("use_folder_components") is True
    # Explicit file IDs must NOT be in the YAML (subfolders will provide them)
    assert "cover_file_id" not in parsed
    assert "preface_file_ids" not in parsed


def test_convert_edition_creates_songs_subfolder(runner, mocker):
    """editions convert creates a Songs subfolder with shortcuts for each song file."""
    from ..worker.models import File as DriveFile

    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.side_effect = ["edition_folder_id", "songs_sub_id"]
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mock_instance.create_shortcut.return_value = "shortcut_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)
    song_files = [
        DriveFile(id="s1", name="Alpha Song"),
        DriveFile(id="s2", name="Beta Song"),
        DriveFile(id="s3", name="Gamma Song"),
    ]
    mocker.patch(
        "generator.cli.editions.collect_and_sort_files", return_value=song_files
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Songs" in result.output
    assert "3 song shortcut" in result.output

    # create_folder: edition folder + Songs subfolder
    assert mock_instance.create_folder.call_count == 2
    folder_names = [c[0][0] for c in mock_instance.create_folder.call_args_list]
    assert "Songs" in folder_names

    # 3 song shortcuts, each with the song's name
    assert mock_instance.create_shortcut.call_count == 3
    shortcut_args = [c[0] for c in mock_instance.create_shortcut.call_args_list]
    shortcut_names = [a[0] for a in shortcut_args]
    assert "Alpha Song" in shortcut_names
    assert "Beta Song" in shortcut_names
    assert "Gamma Song" in shortcut_names
    # All shortcuts point to the Songs subfolder
    shortcut_parents = [a[2] for a in shortcut_args]
    assert all(p == "songs_sub_id" for p in shortcut_parents)


def test_convert_edition_collects_songs_with_filter(runner, mocker):
    """editions convert calls collect_and_sort_files with the edition's filters."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mock_instance.create_shortcut.return_value = "shortcut_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)
    mock_collect = mocker.patch(
        "generator.cli.editions.collect_and_sort_files", return_value=[]
    )

    result = runner.invoke(
        cli,
        ["editions", "convert", "test-ed", "--target-folder", "editions_folder"],
    )

    assert result.exit_code == 0, result.output
    # collect_and_sort_files must be called once with the song_sheets source folders
    mock_collect.assert_called_once()
    call_args = mock_collect.call_args
    # First positional arg is gdrive_client, second is source_folder_ids
    source_folders_arg = call_args[0][1]
    assert source_folders_arg == ["song_sheets_folder_id"]


def test_convert_edition_delete_config(runner, mocker, tmp_path):
    """editions convert removes the original YAML file when --delete-config is set."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"

    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\ntitle: Test Edition\n")
    mocker.patch(
        "generator.cli.editions._find_edition_config_path",
        return_value=config_file,
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--no-create-shortcuts",
            "--delete-config",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Deleted config file" in result.output
    assert not config_file.exists()


def test_convert_edition_notes_original_config(runner, mocker, tmp_path):
    """editions convert prints note about original config file when not deleted."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"

    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\n")
    mocker.patch(
        "generator.cli.editions._find_edition_config_path",
        return_value=config_file,
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Note: The original config file" in result.output
    assert config_file.exists()


def test_convert_edition_warns_complex_filters(runner, mocker):
    """editions convert warns when the edition uses FilterGroup."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=[
            {
                "operator": "OR",
                "filters": [
                    {"key": "status", "operator": "equals", "value": "A"},
                    {"key": "status", "operator": "equals", "value": "B"},
                ],
            }
        ],
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "folder",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "complex filter groups" in result.output


def test_convert_edition_drive_init_failure(runner, mocker):
    """editions convert aborts gracefully on Drive init failure."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        side_effect=HttpError(resp=MagicMock(status=403), content=b"Forbidden"),
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "folder",
        ],
    )

    assert result.exit_code != 0
    assert "Failed to initialize Drive services" in result.output


def test_convert_edition_yaml_serialization_roundtrip(runner, mocker):
    """The .songbook.yaml uploaded can be parsed back as a valid Edition."""
    from ..common.config import Edition as CfgEdition

    edition = Edition(
        id="roundtrip-ed",
        title="Roundtrip Edition",
        description="Testing round-trip serialization",
        filters=_CONVERT_FILTERS,
        cover_file_id="cover123",
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch(
        "generator.cli.editions.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    uploaded_content = {}

    def capture_upload(name, content, parent_id, mime_type="application/octet-stream"):
        uploaded_content["content"] = content
        return "yaml_id"

    mock_instance.upload_file_bytes.side_effect = capture_upload
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "roundtrip-ed",
            "--target-folder",
            "folder",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "content" in uploaded_content
    parsed = pyyaml.safe_load(uploaded_content["content"].decode("utf-8"))
    loaded = CfgEdition.model_validate(parsed)
    assert loaded.id == "roundtrip-ed"
    assert loaded.title == "Roundtrip Edition"
    assert loaded.cover_file_id == "cover123"


def test_convert_edition_dry_run_no_drive_calls(runner, mocker):
    """--dry-run makes no Drive API calls and exits cleanly."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mock_init = mocker.patch("generator.cli.editions.init_services")
    mock_gdrive = mocker.patch("generator.cli.editions.GoogleDriveClient")
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    mock_init.assert_not_called()
    mock_gdrive.assert_not_called()
    assert "[DRY RUN]" in result.output
    assert "No changes were made" in result.output


def test_convert_edition_dry_run_shows_folder_and_yaml(runner, mocker):
    """--dry-run prints the folder name, target folder, and .songbook.yaml content."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--dry-run",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Test Edition" in result.output
    assert "editions_folder" in result.output
    assert ".songbook.yaml" in result.output
    assert "test-ed" in result.output


def test_convert_edition_dry_run_shows_shortcuts(runner, mocker):
    """--dry-run lists shortcut names and targets when --create-shortcuts is on."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
        cover_file_id="cover_id",
        preface_file_ids=["preface_id"],
        postface_file_ids=["post1_id", "post2_id"],
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    mocker.patch("generator.cli.editions._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    # Should show Cover/Preface/Postface subfolder structure, not _cover prefixes
    assert "Cover" in result.output
    assert "cover_id" in result.output
    assert "Preface" in result.output
    assert "preface_id" in result.output
    assert "Postface" in result.output
    assert "post1_id" in result.output
    assert "post2_id" in result.output
    # Must NOT use the old flat _cover/_preface prefix convention
    assert "_cover" not in result.output
    assert "_preface" not in result.output
    assert "_postface_01" not in result.output


def test_convert_edition_dry_run_shows_delete_config(runner, mocker, tmp_path):
    """--dry-run with --delete-config shows which file would be deleted."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\n")
    mocker.patch(
        "generator.cli.editions._find_edition_config_path", return_value=config_file
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--dry-run",
            "--no-create-shortcuts",
            "--delete-config",
        ],
    )

    assert result.exit_code == 0, result.output
    assert str(config_file) in result.output
    # The file must NOT have been deleted
    assert config_file.exists()


def test_convert_edition_dry_run_shows_keep_config(runner, mocker, tmp_path):
    """--dry-run without --delete-config shows which file would be kept."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch(
        "generator.cli.editions.get_settings"
    ).return_value = _make_convert_settings(mocker, edition)
    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\n")
    mocker.patch(
        "generator.cli.editions._find_edition_config_path", return_value=config_file
    )

    result = runner.invoke(
        cli,
        [
            "editions",
            "convert",
            "test-ed",
            "--target-folder",
            "editions_folder",
            "--dry-run",
            "--no-create-shortcuts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Keep local config file" in result.output
    assert str(config_file) in result.output
