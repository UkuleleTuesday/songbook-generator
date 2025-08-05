from click.testing import CliRunner
from .cli import cli
from .common.config import get_settings
import pytest


@pytest.fixture
def runner():
    return CliRunner()


def test_generate_command_with_edition(runner, mocker):
    """Test the generate command with a valid edition."""
    mock_generate = mocker.patch("generator.cli.generate_songbook_from_edition")
    mocker.patch("generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock()))

    result = runner.invoke(cli, ["generate", "--edition", "regular"])

    assert result.exit_code == 0
    assert "Generating songbook for edition: regular" in result.output
    mock_generate.assert_called_once()


def test_generate_command_with_invalid_edition(runner, mocker):
    """Test the generate command with an invalid edition."""
    mocker.patch("generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock()))
    result = runner.invoke(cli, ["generate", "--edition", "nonexistent"])

    assert result.exit_code != 0
    assert "Error: Edition 'nonexistent' not found." in result.output
    assert "Available editions: regular, complete" in result.output


def test_generate_command_with_conflicting_flags(runner, mocker):
    """Test that using --edition with conflicting flags fails."""
    mocker.patch("generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock()))
    result = runner.invoke(
        cli, ["generate", "--edition", "regular", "--filter", "artist:Test"]
    )

    assert result.exit_code != 0
    assert "Error: Cannot use --filter with --edition." in result.output


def test_generate_command_legacy_mode(runner, mocker):
    """Test the generate command without an edition (legacy mode)."""
    mock_generate = mocker.patch("generator.cli.generate_songbook")
    mocker.patch("generator.cli.init_services", return_value=(mocker.Mock(), mocker.Mock()))

    result = runner.invoke(
        cli, ["generate", "--filter", "artist:equals:Someone"]
    )

    assert result.exit_code == 0
    assert "Applying client-side filter: artist:equals:Someone" in result.output
    mock_generate.assert_called_once()
