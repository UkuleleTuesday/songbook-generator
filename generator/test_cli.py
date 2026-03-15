from click.testing import CliRunner
from .cli import cli
import pytest
import yaml
from unittest.mock import MagicMock
from googleapiclient.errors import HttpError
from .common.config import Edition


@pytest.fixture
def runner():
    return CliRunner()


def test_generate_command_with_edition(runner, mocker):
    """Test the generate command with a valid edition."""
    mock_generate = mocker.patch("generator.cli.generate_songbook_from_edition")
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )

    result = runner.invoke(cli, ["generate", "--edition", "current"])

    assert result.exit_code == 0
    assert "Generating songbook for edition: current" in result.output
    mock_generate.assert_called_once()


def test_generate_command_with_invalid_edition(runner, mocker):
    """Test the generate command with an unknown edition falls back to Drive."""
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=None,
    )

    result = runner.invoke(cli, ["generate", "--edition", "nonexistent"])

    assert result.exit_code != 0
    assert "not found in configuration" in result.output
    assert "No .songbook.yaml found" in result.output


def test_generate_command_with_conflicting_flags(runner, mocker):
    """Test that using --edition with conflicting flags fails."""
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    result = runner.invoke(
        cli, ["generate", "--edition", "current", "--filter", "artist:Test"]
    )

    assert result.exit_code != 0
    assert "Error: Cannot use --filter with --edition." in result.output


def test_generate_command_legacy_mode(runner, mocker):
    """Test the generate command without an edition (legacy mode)."""
    mock_generate = mocker.patch("generator.cli.generate_songbook")
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )

    result = runner.invoke(cli, ["generate", "--filter", "artist:equals:Someone"])

    assert result.exit_code == 0
    assert "Applying client-side filter: artist:equals:Someone" in result.output
    mock_generate.assert_called_once()


def _make_edition_yaml(**overrides):
    """Helper: return a minimal valid .songbook.yaml as bytes."""
    data = {
        "id": "drive-edition",
        "title": "Drive Edition",
        "description": "Generated from Drive folder",
        "filters": [{"key": "specialbooks", "operator": "contains", "value": "test"}],
    }
    data.update(overrides)
    return yaml.dump(data).encode("utf-8")


def test_generate_command_with_edition_as_folder_id(runner, mocker):
    """--edition with a Drive folder ID reads .songbook.yaml and generates."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()
    mock_generate = mocker.patch("generator.cli.generate_songbook_from_edition")
    mocker.patch("generator.cli.init_services", return_value=(mock_drive, mock_cache))
    mock_file = mocker.Mock()
    mock_file.id = "yaml-file-id"
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=mock_file,
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.download_raw_bytes",
        return_value=_make_edition_yaml(),
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code == 0, result.output
    assert "drive-edition" in result.output
    mock_generate.assert_called_once()
    call_kwargs = mock_generate.call_args.kwargs
    assert call_kwargs["drive"] is mock_drive
    assert call_kwargs["cache"] is mock_cache
    edition_arg = call_kwargs["edition"]
    assert edition_arg.id == "drive-edition"
    assert edition_arg.title == "Drive Edition"


def test_generate_command_edition_as_folder_id_missing_yaml(runner, mocker):
    """--edition with Drive folder ID aborts when .songbook.yaml is missing."""
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=None,
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code != 0
    assert "No .songbook.yaml found" in result.output


def test_generate_command_edition_as_folder_id_invalid_yaml(runner, mocker):
    """--edition with Drive folder ID aborts when .songbook.yaml is invalid YAML."""
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mock_file = mocker.Mock()
    mock_file.id = "yaml-file-id"
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=mock_file,
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.download_raw_bytes",
        return_value=b": invalid: yaml: {{{",
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code != 0
    assert "Failed to parse .songbook.yaml" in result.output


def test_generate_command_edition_as_folder_id_invalid_schema(runner, mocker):
    """--edition with Drive folder ID aborts when .songbook.yaml has wrong schema."""
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mock_file = mocker.Mock()
    mock_file.id = "yaml-file-id"
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=mock_file,
    )
    # Missing required fields (id, title, description, filters)
    mocker.patch(
        "generator.cli.GoogleDriveClient.download_raw_bytes",
        return_value=b"just_a_string: true",
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code != 0
    assert "does not match the Edition schema" in result.output


def test_generate_command_edition_as_folder_id_conflicting_flags(runner, mocker):
    """--edition as Drive folder ID still rejects --filter and related flags."""
    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )

    result = runner.invoke(
        cli,
        [
            "generate",
            "--edition",
            "folder-abc123",
            "--filter",
            "artist:equals:Test",
        ],
    )

    assert result.exit_code != 0
    assert "Cannot use --filter with --edition" in result.output


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
    mocker.patch("generator.cli.get_settings").return_value = mocker.Mock(
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
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    drive_edition = Edition(
        id="drive-ed",
        title="Drive Songbook",
        description=_EDITION_DESCRIPTION,
        filters=_EDITION_FILTERS,
    )
    mocker.patch(
        "generator.cli.scan_drive_editions",
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
    mocker.patch("generator.cli.get_settings").return_value = mocker.Mock(
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
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mocker.patch("generator.cli.scan_drive_editions", return_value=[])

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
    mocker.patch("generator.cli.get_settings").return_value = mocker.Mock(
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
        "generator.cli.init_services",
        side_effect=HttpError(resp=MagicMock(status=403), content=b"Forbidden"),
    )

    result = runner.invoke(cli, ["editions", "list"])

    assert result.exit_code == 0
    assert "Config editions:" in result.output
    assert "Drive scan failed" in result.output


def test_editions_list_no_config_editions(runner, mocker):
    """editions list reports when no config editions exist."""
    mocker.patch("generator.cli.get_settings").return_value = mocker.Mock(
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
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mocker.patch("generator.cli.scan_drive_editions", return_value=[])

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
        google_cloud=mocker.Mock(
            credentials={
                "songbook-generator": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        songbook_editions=mocker.Mock(
            folder_ids=folder_ids if folder_ids is not None else ["editions_folder"]
        ),
    )


def test_convert_edition_success(runner, mocker):
    """editions convert creates a Drive folder and uploads .songbook.yaml."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "new_folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_file_id"
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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


def test_convert_edition_custom_folder_name(runner, mocker):
    """editions convert uses --folder-name when provided."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    mocker.patch("generator.cli.get_settings").return_value = mocker.Mock(
        editions=[],
        google_cloud=mocker.Mock(credentials={}),
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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition, folder_ids=[]
    )

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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition, folder_ids=["only_folder"]
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

    result = runner.invoke(
        cli,
        ["editions", "convert", "test-ed", "--no-create-shortcuts"],
    )

    assert result.exit_code == 0, result.output
    mock_instance.create_folder.assert_called_once_with("Test Edition", "only_folder")


def test_convert_edition_creates_shortcuts(runner, mocker):
    """editions convert creates shortcuts for cover, preface, and postface."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
        cover_file_id="cover_id",
        preface_file_ids=["preface_id"],
        postface_file_ids=["post1_id", "post2_id"],
    )
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mock_instance.create_shortcut.return_value = "shortcut_id"
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    assert "Creating component shortcuts" in result.output
    # Four shortcuts: _cover, _preface, _postface_01, _postface_02
    assert mock_instance.create_shortcut.call_count == 4
    calls = [c[0] for c in mock_instance.create_shortcut.call_args_list]
    shortcut_names = [c[0] for c in calls]
    assert "_cover" in shortcut_names
    assert "_preface" in shortcut_names
    assert "_postface_01" in shortcut_names
    assert "_postface_02" in shortcut_names


def test_convert_edition_delete_config(runner, mocker, tmp_path):
    """editions convert removes the original YAML file when --delete-config is set."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"

    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\ntitle: Test Edition\n")
    mocker.patch(
        "generator.cli._find_edition_config_path",
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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"

    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\n")
    mocker.patch(
        "generator.cli._find_edition_config_path",
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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    mock_instance.upload_file_bytes.return_value = "yaml_id"
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    from unittest.mock import MagicMock

    mocker.patch(
        "generator.cli.init_services",
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
    import yaml as pyyaml
    from .common.config import Edition as CfgEdition

    edition = Edition(
        id="roundtrip-ed",
        title="Roundtrip Edition",
        description="Testing round-trip serialization",
        filters=_CONVERT_FILTERS,
        cover_file_id="cover123",
    )
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch(
        "generator.cli.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mock_instance = mock_gdrive.return_value
    mock_instance.create_folder.return_value = "folder_id"
    uploaded_content = {}

    def capture_upload(name, content, parent_id, mime_type="application/octet-stream"):
        uploaded_content["content"] = content
        return "yaml_id"

    mock_instance.upload_file_bytes.side_effect = capture_upload
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mock_init = mocker.patch("generator.cli.init_services")
    mock_gdrive = mocker.patch("generator.cli.GoogleDriveClient")
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    mocker.patch("generator.cli._find_edition_config_path", return_value=None)

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
    assert "_cover" in result.output
    assert "cover_id" in result.output
    assert "_preface" in result.output
    assert "preface_id" in result.output
    assert "_postface_01" in result.output
    assert "_postface_02" in result.output


def test_convert_edition_dry_run_shows_delete_config(runner, mocker, tmp_path):
    """--dry-run with --delete-config shows which file would be deleted."""
    edition = Edition(
        id="test-ed",
        title="Test Edition",
        description=_CONVERT_DESCRIPTION,
        filters=_CONVERT_FILTERS,
    )
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\n")
    mocker.patch("generator.cli._find_edition_config_path", return_value=config_file)

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
    mocker.patch("generator.cli.get_settings").return_value = _make_convert_settings(
        mocker, edition
    )
    config_file = tmp_path / "test-ed.yaml"
    config_file.write_text("id: test-ed\n")
    mocker.patch("generator.cli._find_edition_config_path", return_value=config_file)

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
