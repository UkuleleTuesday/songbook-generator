import csv
import io
import json

import pytest
from click.testing import CliRunner

from ..cli import cli


@pytest.fixture
def runner():
    return CliRunner()


_DOCS = {
    "fileB": {
        "gdrive_file_id": "fileB",
        "gdrive_file_name": "Yellow - Coldplay",
        "properties": {"artist": "Coldplay", "year": "2000", "genre": "rock"},
        "metadata_updated_at": "2026-06-18T14:30:00Z",
    },
    "fileA": {
        "gdrive_file_id": "fileA",
        "gdrive_file_name": "Let It Be - The Beatles",
        "properties": {"artist": "The Beatles", "song": "Let It Be"},
        "metadata_updated_at": "2026-06-17T09:00:00Z",
    },
}


def _mock_firestore_export(mocker):
    """Patch tags export to read the sample docs from a fake Firestore store."""
    mocker.patch("generator.cli.tags.get_settings").return_value = mocker.Mock(
        metadata_store=mocker.Mock(firestore_read_enabled=True),
    )
    store = mocker.Mock()
    store.get_all.return_value = _DOCS
    mocker.patch("generator.cli.tags.get_metadata_store", return_value=store)


def test_export_json_to_stdout_is_newline_delimited(runner, mocker):
    _mock_firestore_export(mocker)

    result = runner.invoke(cli, ["tags", "export", "--format", "json"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    # One object per line, sorted by file ID (fileA before fileB).
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["gdrive_file_id"] == "fileA"
    assert second["gdrive_file_id"] == "fileB"
    assert first["properties"]["song"] == "Let It Be"


def test_export_json_is_default_format(runner, mocker):
    _mock_firestore_export(mocker)

    result = runner.invoke(cli, ["tags", "export"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)


def test_export_csv_columns_are_union_of_property_keys(runner, mocker):
    _mock_firestore_export(mocker)

    result = runner.invoke(cli, ["tags", "export", "--format", "csv"])

    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(result.output)))
    reader = csv.reader(io.StringIO(result.output))
    header = next(reader)
    # Identifying columns first, then the sorted union of all property keys.
    assert header == [
        "gdrive_file_id",
        "gdrive_file_name",
        "artist",
        "genre",
        "song",
        "year",
    ]
    assert len(rows) == 2
    beatles = next(r for r in rows if r["gdrive_file_id"] == "fileA")
    assert beatles["song"] == "Let It Be"
    # A property absent from this doc renders as an empty cell.
    assert beatles["genre"] == ""


def test_export_writes_to_output_file(runner, mocker, tmp_path):
    _mock_firestore_export(mocker)
    out_file = tmp_path / "songs.jsonl"

    result = runner.invoke(
        cli, ["tags", "export", "--format", "json", "--output", str(out_file)]
    )

    assert result.exit_code == 0, result.output
    lines = [line for line in out_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["gdrive_file_id"] == "fileA"
    # Stdout stays clean; the summary goes to stderr.
    assert "Exported 2 song(s)" in result.output


def test_export_strips_unknown_date_sentinels(runner, mocker):
    """The literal "unknown" sentinel is dropped from exported date fields (#442)."""
    docs = {
        "fileA": {
            "gdrive_file_id": "fileA",
            "gdrive_file_name": "Luka - Suzanne Vega",
            "properties": {
                "artist": "Suzanne Vega",
                "ready_to_play_date": "unknown",
                "approved_date": "unknown",
                "year": "1987",
            },
        },
        "fileB": {
            "gdrive_file_id": "fileB",
            "gdrive_file_name": "Roar - Katy Perry",
            "properties": {
                "ready_to_play_date": "2023-06-20T10:02:00Z",
                "approved_date": "unknown",
            },
        },
    }
    mocker.patch("generator.cli.tags.get_settings").return_value = mocker.Mock(
        metadata_store=mocker.Mock(firestore_read_enabled=True),
    )
    store = mocker.Mock()
    store.get_all.return_value = docs
    mocker.patch("generator.cli.tags.get_metadata_store", return_value=store)

    result = runner.invoke(cli, ["tags", "export", "--format", "json"])

    assert result.exit_code == 0, result.output
    by_id = {
        json.loads(line)["gdrive_file_id"]: json.loads(line)
        for line in result.output.splitlines()
        if line.strip()
    }
    # Both "unknown" date fields are gone; real values and other props survive.
    assert "ready_to_play_date" not in by_id["fileA"]["properties"]
    assert "approved_date" not in by_id["fileA"]["properties"]
    assert by_id["fileA"]["properties"]["year"] == "1987"
    assert by_id["fileB"]["properties"]["ready_to_play_date"] == "2023-06-20T10:02:00Z"
    assert "approved_date" not in by_id["fileB"]["properties"]


def test_export_falls_back_to_drive_when_firestore_read_disabled(runner, mocker):
    from ..worker.models import File

    mocker.patch("generator.cli.tags.get_settings").return_value = mocker.Mock(
        metadata_store=mocker.Mock(firestore_read_enabled=False),
        google_cloud=mocker.Mock(
            credentials={
                "songbook-metadata-writer": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            }
        ),
        song_sheets=mocker.Mock(folder_ids=["folder1"]),
    )
    mocker.patch(
        "generator.cli.tags.init_services",
        return_value=(mocker.Mock(), mocker.Mock()),
    )
    gdrive_client = mocker.Mock()
    gdrive_client.query_drive_files.return_value = [
        File(
            id="fileA", name="Let It Be - The Beatles", properties={"song": "Let It Be"}
        ),
    ]
    mocker.patch("generator.cli.tags.GoogleDriveClient", return_value=gdrive_client)

    result = runner.invoke(cli, ["tags", "export", "--format", "json"])

    assert result.exit_code == 0, result.output
    # stderr (the fallback notice) is mixed into output; keep only JSON lines.
    lines = [line for line in result.output.splitlines() if line.startswith("{")]
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc["gdrive_file_id"] == "fileA"
    assert doc["properties"] == {"song": "Let It Be"}
    # Drive fallback has no Firestore timestamp.
    assert "metadata_updated_at" not in doc


def _mock_update_services(mocker, query_result):
    """Patch the Drive/Docs plumbing behind `tags update` to a fake client."""
    mocker.patch("generator.cli.tags.get_settings").return_value = mocker.Mock(
        google_cloud=mocker.Mock(
            credentials={
                "tag-updater": mocker.Mock(
                    scopes=["https://www.googleapis.com/auth/drive"],
                    principal="sa@project.iam.gserviceaccount.com",
                )
            },
            project_id="proj",
        ),
        song_sheets=mocker.Mock(folder_ids=["folder1"]),
        tag_updater=mocker.Mock(trigger_field=None, llm_tagging_enabled=False),
        metadata_store=mocker.Mock(firestore_write_enabled=False),
        caching=mocker.Mock(gcs=mocker.Mock(region="europe-west1")),
    )
    mocker.patch("generator.cli.tags.get_credentials")
    mocker.patch("generator.cli.tags.build")
    mocker.patch("generator.cli.tags.init_cache")
    gdrive_client = mocker.Mock()
    gdrive_client.query_drive_files.return_value = query_result
    mocker.patch("generator.cli.tags.GoogleDriveClient", return_value=gdrive_client)
    mocker.patch("generator.cli.tags.Tagger")
    return gdrive_client


def test_update_modified_since_filters_the_drive_query(runner, mocker):
    from datetime import datetime

    from ..worker.models import File

    gdrive_client = _mock_update_services(
        mocker,
        [File(id="fileA", name="Let It Be - The Beatles", properties={})],
    )

    result = runner.invoke(
        cli, ["tags", "update", "--modified-since", "2026-09-28T10:51:00", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    gdrive_client.query_drive_files.assert_called_once_with(
        ["folder1"], modified_after=datetime(2026, 9, 28, 10, 51, 0)
    )
    assert "Found 1 file(s) modified since cutoff." in result.output


def test_update_modified_since_rejects_a_file_identifier(runner, mocker):
    _mock_update_services(mocker, [])

    result = runner.invoke(
        cli, ["tags", "update", "Let It Be", "--modified-since", "2026-09-28"]
    )

    assert result.exit_code != 0
    assert "Cannot use both a file identifier and --modified-since" in result.output


def test_update_requires_a_selector(runner, mocker):
    _mock_update_services(mocker, [])

    result = runner.invoke(cli, ["tags", "update"])

    assert result.exit_code != 0
    assert "--modified-since" in result.output
