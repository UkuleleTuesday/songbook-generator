from datetime import datetime

import pytest
from click.testing import CliRunner

from ..cli import cli
from ..worker.models import File


@pytest.fixture
def runner():
    return CliRunner()


def _mock_list_services(mocker, files):
    """Patch the Drive plumbing behind `songs list` to a fake song source."""
    mocker.patch("generator.cli.songs.get_settings").return_value = mocker.Mock(
        google_cloud=mocker.Mock(
            credentials={
                "songbook-generator": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive.readonly"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        song_sheets=mocker.Mock(folder_ids=["folder1"]),
    )
    mocker.patch(
        "generator.cli.songs.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    song_source = mocker.Mock()
    song_source.collect_files.return_value = files
    mocker.patch("generator.cli.songs._make_song_source", return_value=song_source)
    return song_source


def test_list_modified_since_filters_the_drive_query(runner, mocker):
    song_source = _mock_list_services(
        mocker, [File(id="fileA", name="Wind of Change - Scorpions", properties={})]
    )

    result = runner.invoke(
        cli,
        [
            "songs",
            "list",
            "--source-folder",
            "folder1",
            "--modified-since",
            "2026-07-11T20:49:19",
        ],
    )

    assert result.exit_code == 0, result.output
    song_source.collect_files.assert_called_once_with(
        ["folder1"], None, modified_after=datetime(2026, 7, 11, 20, 49, 19)
    )
    assert "Wind of Change - Scorpions" in result.output


def test_list_modified_since_narrows_with_a_filter(runner, mocker):
    song_source = _mock_list_services(mocker, [])

    result = runner.invoke(
        cli,
        [
            "songs",
            "list",
            "--source-folder",
            "folder1",
            "--modified-since",
            "2026-07-11",
            "--filter",
            "status:READY_TO_PLAY",
        ],
    )

    assert result.exit_code == 0, result.output
    _, _, kwargs = song_source.collect_files.mock_calls[0]
    assert kwargs["modified_after"] == datetime(2026, 7, 11)
    assert song_source.collect_files.call_args[0][1] is not None


def test_list_still_requires_one_selector(runner, mocker):
    _mock_list_services(mocker, [])

    result = runner.invoke(cli, ["songs", "list"])

    assert result.exit_code != 0
    assert "--modified-since" in result.output
