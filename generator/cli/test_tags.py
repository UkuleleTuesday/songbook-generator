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
