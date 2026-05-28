"""Tests for the ``generate-pptx`` CLI command."""

import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError

from ..cli import cli
from ..worker.models import File


@pytest.fixture
def runner():
    return CliRunner()


def _make_mock_file(name="Love Me Do - Beatles", file_id="file-id-123"):
    f = File(
        id=file_id,
        name=name,
        mimeType="application/vnd.google-apps.document",
        properties={},
        parents=[],
    )
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Happy-path tests
# ─────────────────────────────────────────────────────────────────────────────


def test_generate_pptx_command_success(runner, mocker, tmp_path):
    """generate-pptx resolves the file, exports as text and writes PPTX."""
    mock_file = _make_mock_file()
    mocker.patch(
        "generator.cli.pptx.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.get_files_metadata_by_ids",
        return_value=[mock_file],
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.search_files_by_name",
        return_value=[mock_file],
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.export_as_plain_text",
        return_value="[G]Hello world\n\n[C]Chorus",
    )
    out = tmp_path / "out.pptx"
    result = runner.invoke(
        cli,
        ["generate-pptx", "Love Me Do", "--destination-path", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert "✅ PPTX saved to" in result.output
    assert out.exists()


def test_generate_pptx_command_default_output_path(runner, mocker, tmp_path):
    """generate-pptx defaults to out/song.pptx."""
    mock_file = _make_mock_file()
    mocker.patch(
        "generator.cli.pptx.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.get_files_metadata_by_ids",
        return_value=[mock_file],
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.search_files_by_name",
        return_value=[mock_file],
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.export_as_plain_text",
        return_value="[G]Hello",
    )

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["generate-pptx", "Love Me Do"])

    assert result.exit_code == 0, result.output
    assert "out/song.pptx" in result.output


# ─────────────────────────────────────────────────────────────────────────────
# Error cases
# ─────────────────────────────────────────────────────────────────────────────


def test_generate_pptx_missing_credential_config(runner, mocker):
    """Aborts when 'songbook-generator' credential config is missing."""
    settings = mocker.patch("generator.cli.pptx.get_settings")
    settings.return_value.google_cloud.credentials = {}

    result = runner.invoke(cli, ["generate-pptx", "Some Song"])

    assert result.exit_code != 0
    assert "credential config 'songbook-generator' not found" in result.output


def test_generate_pptx_song_not_found(runner, mocker):
    """Aborts when the song cannot be resolved."""
    mocker.patch(
        "generator.cli.pptx.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.search_files_by_name",
        return_value=[],
    )

    result = runner.invoke(cli, ["generate-pptx", "Unknown Song"])

    assert result.exit_code != 0
    assert "No file found" in result.output


def test_generate_pptx_metadata_retrieval_fails(runner, mocker, tmp_path):
    """Aborts when metadata cannot be retrieved for the resolved file ID."""
    mock_file = _make_mock_file()
    mocker.patch(
        "generator.cli.pptx.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.search_files_by_name",
        return_value=[mock_file],
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.get_files_metadata_by_ids",
        return_value=[],
    )

    result = runner.invoke(
        cli,
        ["generate-pptx", "Love Me Do", "--destination-path", str(tmp_path / "x.pptx")],
    )

    assert result.exit_code != 0
    assert "Could not retrieve metadata" in result.output


def test_generate_pptx_export_http_error(runner, mocker, tmp_path):
    """Aborts and shows error when Google Drive export fails."""
    mock_file = _make_mock_file()
    mocker.patch(
        "generator.cli.pptx.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.get_files_metadata_by_ids",
        return_value=[mock_file],
    )
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.search_files_by_name",
        return_value=[mock_file],
    )
    mock_resp = mocker.Mock()
    mock_resp.status = 403
    mock_resp.reason = "Forbidden"
    mocker.patch(
        "generator.cli.pptx.GoogleDriveClient.export_as_plain_text",
        side_effect=HttpError(resp=mock_resp, content=b"Forbidden"),
    )

    result = runner.invoke(
        cli,
        ["generate-pptx", "Love Me Do", "--destination-path", str(tmp_path / "x.pptx")],
    )

    assert result.exit_code != 0
    assert "Could not export document as plain text" in result.output
