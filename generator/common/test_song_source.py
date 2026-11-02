"""Tests for SongSheetSource — Drive file existence + Firestore properties."""

from unittest.mock import Mock

from ..worker.models import File
from .filters import PropertyFilter
from .gdrive import GoogleDriveClient
from .metadata_store import SongMetadataStore
from .song_source import SongSheetSource
from .test_metadata_store import FakeFirestore


def _make_source(files, metadata: dict | None = None) -> SongSheetSource:
    gdrive = Mock(spec=GoogleDriveClient)
    gdrive.query_drive_files.return_value = files

    db = FakeFirestore()
    store = SongMetadataStore(db=db, collection="song-metadata")
    for file_id, props in (metadata or {}).items():
        store.write(file_id, props)
    return SongSheetSource(gdrive, store)


READY_FILTER = PropertyFilter(key="status", operator="equals", value="READY_TO_PLAY")


def test_properties_come_from_firestore():
    files = [File(id="a", name="Song A")]
    source = _make_source(files, metadata={"a": {"status": "APPROVED", "year": "2020"}})

    result = source.collect_files(["folder1"])

    assert result[0].properties == {"status": "APPROVED", "year": "2020"}


def test_file_without_firestore_doc_is_untagged(capsys):
    files = [
        File(id="a", name="Song A"),
        File(id="b", name="Song B"),
    ]
    source = _make_source(files, metadata={"a": {"status": "READY_TO_PLAY"}})

    result = source.collect_files(["folder1"])

    assert result[0].properties == {"status": "READY_TO_PLAY"}
    assert result[1].properties == {}
    err = capsys.readouterr().err
    assert "1 song sheet(s) have no Firestore metadata" in err
    assert "Song B (b)" in err


def test_filter_uses_firestore_properties():
    files = [File(id="a", name="Song A")]
    source = _make_source(files, metadata={"a": {"status": "READY_TO_PLAY"}})

    result = source.collect_files(["folder1"], READY_FILTER)

    assert [f.id for f in result] == ["a"]


def test_filter_excludes_file_without_firestore_doc():
    files = [File(id="a", name="Song A")]
    source = _make_source(files)

    assert source.collect_files(["folder1"], READY_FILTER) == []


def test_filter_can_match_on_name():
    files = [File(id="a", name="Song A"), File(id="b", name="Song B")]
    source = _make_source(files, metadata={"a": {}, "b": {}})
    name_filter = PropertyFilter(key="name", operator="equals", value="Song B")

    assert [f.id for f in source.collect_files(["folder1"], name_filter)] == ["b"]


def test_drive_query_passes_folders_and_cutoff():
    source = _make_source([])

    source.collect_files(["folder1"], READY_FILTER)

    source._gdrive.query_drive_files.assert_called_once_with(
        ["folder1"], modified_after=None
    )


def test_list_folder_returns_files_with_properties():
    source = _make_source([], metadata={"a": {"difficulty": "2.5"}})
    source._gdrive.list_folder_contents.return_value = [
        File(id="a", name="Song A"),
        File(id="b", name="Song B"),
    ]

    result = source.list_folder("folder1", resolve_shortcuts=True)

    assert [f.properties for f in result] == [{"difficulty": "2.5"}, {}]
    source._gdrive.list_folder_contents.assert_called_once_with(
        "folder1", resolve_shortcuts=True
    )


def test_get_files_returns_files_with_properties():
    source = _make_source([], metadata={"a": {"status": "APPROVED"}})
    source._gdrive.get_files_metadata_by_ids.return_value = [
        File(id="a", name="Song A")
    ]

    result = source.get_files(["a"])

    assert result[0].properties == {"status": "APPROVED"}
    source._gdrive.get_files_metadata_by_ids.assert_called_once_with(["a"])
