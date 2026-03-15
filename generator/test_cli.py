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
    """Test the generate command with an unknown edition falls back to Drive.

    When no .songbook.yaml is found a default edition is built using the
    folder's display name, so generation proceeds rather than erroring out.
    """
    from .worker.models import File as WFile

    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=None,
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.get_file_metadata",
        return_value=WFile(id="nonexistent", name="Nonexistent Folder"),
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_subfolder_by_name", return_value=None
    )
    mock_generate = mocker.patch("generator.cli.generate_songbook_from_edition")

    result = runner.invoke(cli, ["generate", "--edition", "nonexistent"])

    assert result.exit_code == 0
    assert "not found in configuration" in result.output
    mock_generate.assert_called_once()
    # Verify the default edition was built with the folder's display name
    called_edition = mock_generate.call_args.kwargs["edition"]
    assert called_edition.title == "Nonexistent Folder"
    assert called_edition.use_folder_components is True


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
    """--edition with Drive folder ID succeeds with defaults when .songbook.yaml
    is absent from the folder."""
    from .worker.models import File as WFile

    mocker.patch(
        "generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock())
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_file_in_folder",
        return_value=None,
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.get_file_metadata",
        return_value=WFile(id="folder-abc123", name="ABC123 Folder"),
    )
    mocker.patch(
        "generator.cli.GoogleDriveClient.find_subfolder_by_name", return_value=None
    )
    mock_generate = mocker.patch("generator.cli.generate_songbook_from_edition")

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code == 0
    mock_generate.assert_called_once()
    called_edition = mock_generate.call_args.kwargs["edition"]
    assert called_edition.id == "folder-abc123"
    assert called_edition.title == "ABC123 Folder"
    assert called_edition.use_folder_components is True


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
