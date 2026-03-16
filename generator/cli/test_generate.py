import pytest
import yaml
from click.testing import CliRunner

from ..cli import cli


@pytest.fixture
def runner():
    return CliRunner()


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


def test_generate_command_with_edition(runner, mocker):
    """Test the generate command with a valid edition."""
    mock_generate = mocker.patch(
        "generator.cli.generate.generate_songbook_from_edition"
    )
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )

    result = runner.invoke(cli, ["generate", "--edition", "current"])

    assert result.exit_code == 0
    assert "Generating songbook for edition: current" in result.output
    mock_generate.assert_called_once()


def test_generate_command_with_invalid_edition(runner, mocker):
    """Test the generate command with an unknown edition falls back to Drive."""
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.find_file_in_folder",
        return_value=None,
    )

    result = runner.invoke(cli, ["generate", "--edition", "nonexistent"])

    assert result.exit_code != 0
    assert "not found in configuration" in result.output
    assert "No .songbook.yaml found" in result.output


def test_generate_command_with_conflicting_flags(runner, mocker):
    """Test that using --edition with conflicting flags fails."""
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    result = runner.invoke(
        cli, ["generate", "--edition", "current", "--filter", "artist:Test"]
    )

    assert result.exit_code != 0
    assert "Error: Cannot use --filter with --edition." in result.output


def test_generate_command_legacy_mode(runner, mocker):
    """Test the generate command without an edition (legacy mode)."""
    mock_generate = mocker.patch("generator.cli.generate.generate_songbook")
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )

    result = runner.invoke(cli, ["generate", "--filter", "artist:equals:Someone"])

    assert result.exit_code == 0
    assert "Applying client-side filter: artist:equals:Someone" in result.output
    mock_generate.assert_called_once()


def test_generate_command_with_edition_as_folder_id(runner, mocker):
    """--edition with a Drive folder ID reads .songbook.yaml and generates."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()
    mock_generate = mocker.patch(
        "generator.cli.generate.generate_songbook_from_edition"
    )
    mocker.patch(
        "generator.cli.generate.init_services", return_value=(mock_drive, mock_cache)
    )
    mock_file = mocker.Mock()
    mock_file.id = "yaml-file-id"
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.find_file_in_folder",
        return_value=mock_file,
    )
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.download_raw_bytes",
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
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.find_file_in_folder",
        return_value=None,
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code != 0
    assert "No .songbook.yaml found" in result.output


def test_generate_command_edition_as_folder_id_invalid_yaml(runner, mocker):
    """--edition with Drive folder ID aborts when .songbook.yaml is invalid YAML."""
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_file = mocker.Mock()
    mock_file.id = "yaml-file-id"
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.find_file_in_folder",
        return_value=mock_file,
    )
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.download_raw_bytes",
        return_value=b": invalid: yaml: {{{",
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code != 0
    assert "Failed to parse .songbook.yaml" in result.output


def test_generate_command_edition_as_folder_id_invalid_schema(runner, mocker):
    """--edition with Drive folder ID aborts when .songbook.yaml has wrong schema."""
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mock_file = mocker.Mock()
    mock_file.id = "yaml-file-id"
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.find_file_in_folder",
        return_value=mock_file,
    )
    # Missing required fields (id, title, description, filters)
    mocker.patch(
        "generator.cli.generate.GoogleDriveClient.download_raw_bytes",
        return_value=b"just_a_string: true",
    )

    result = runner.invoke(cli, ["generate", "--edition", "folder-abc123"])

    assert result.exit_code != 0
    assert "does not match the Edition schema" in result.output


def test_generate_command_edition_as_folder_id_conflicting_flags(runner, mocker):
    """--edition as Drive folder ID still rejects --filter and related flags."""
    mocker.patch(
        "generator.cli.generate.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
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
