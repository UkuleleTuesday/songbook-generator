import pytest
from click.testing import CliRunner

from ..cli import cli

_DOCS = {
    "fileA": {
        "gdrive_file_id": "fileA",
        "gdrive_file_name": "Let It Be - The Beatles",
        "properties": {"artist": "The Beatles", "theme": "pride"},
        "metadata_updated_at": "2026-06-17T09:00:00Z",
    },
    "fileB": {
        "gdrive_file_id": "fileB",
        "gdrive_file_name": "Yellow - Coldplay",
        "properties": {"artist": "Coldplay", "year": "2000"},
        "metadata_updated_at": "2026-06-18T14:30:00Z",
    },
}


@pytest.fixture
def runner():
    return CliRunner()


def _patch_stores(mocker, source_docs):
    """Patch get_metadata_store: the default DB is the source, a named DB the dest."""
    source = mocker.Mock()
    source.get_all.return_value = source_docs
    dest = mocker.Mock()
    dest.collection = "song-metadata"
    dest.written_items = []

    def _bulk(items):
        materialized = list(items)
        dest.written_items = materialized
        return len(materialized)

    dest.bulk_write.side_effect = _bulk

    def _factory(*args, database=None, **kwargs):
        return source if database in (None, "") else dest

    mocker.patch("generator.cli.metadata.get_metadata_store", side_effect=_factory)
    return source, dest


def test_copy_writes_all_documents_to_destination(runner, mocker):
    source, dest = _patch_stores(mocker, _DOCS)

    result = runner.invoke(cli, ["metadata", "copy", "--dest-database", "pr-421"])

    assert result.exit_code == 0, result.output
    assert "Read 2 documents" in result.output
    assert "Copied 2 documents to database 'pr-421'" in result.output

    dest.bulk_write.assert_called_once()
    by_id = {file_id: (props, name) for file_id, props, name in dest.written_items}
    assert set(by_id) == {"fileA", "fileB"}
    # Properties (including Firestore-only tags like theme=pride) are preserved.
    assert by_id["fileA"] == (
        {"artist": "The Beatles", "theme": "pride"},
        "Let It Be - The Beatles",
    )


def test_copy_dry_run_does_not_write(runner, mocker):
    _source, dest = _patch_stores(mocker, _DOCS)

    result = runner.invoke(
        cli, ["metadata", "copy", "--dest-database", "pr-421", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN: would write 2 documents to 'pr-421'." in result.output
    dest.bulk_write.assert_not_called()


def test_copy_refuses_identical_source_and_dest(runner, mocker):
    _patch_stores(mocker, _DOCS)

    result = runner.invoke(
        cli,
        ["metadata", "copy", "--source-database", "pr-1", "--dest-database", "pr-1"],
    )

    assert result.exit_code != 0
    assert "identical" in result.output
