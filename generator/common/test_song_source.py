"""Tests for SongSheetSource — Drive file existence + optional Firestore property overlay."""

from unittest.mock import Mock

from ..worker.models import File
from .filters import PropertyFilter
from .gdrive import GoogleDriveClient
from .metadata_store import SongMetadataStore
from .song_source import SongSheetSource
from .test_metadata_store import FakeFirestore


def _make_source(files, metadata: dict | None = None) -> SongSheetSource:
    gdrive = Mock(spec=GoogleDriveClient)

    def _query(source_folders, client_filter=None, modified_after=None):
        # Mirror GoogleDriveClient: filter on the Drive properties it returns.
        if not client_filter:
            return files
        return [
            f for f in files if client_filter.matches({**f.properties, "name": f.name})
        ]

    gdrive.query_drive_files_with_client_filter.side_effect = _query

    if metadata is None:
        return SongSheetSource(gdrive)

    db = FakeFirestore()
    store = SongMetadataStore(db=db, collection="song-metadata")
    for file_id, props in metadata.items():
        store.write(file_id, props)
    return SongSheetSource(gdrive, store)


def test_drive_mode_returns_drive_properties():
    files = [File(id="a", name="Song A", properties={"status": "APPROVED"})]
    source = _make_source(files)

    result = source.collect_files(["folder1"])

    assert result[0].properties == {"status": "APPROVED"}


def test_firestore_mode_overlays_properties():
    files = [File(id="a", name="Song A", properties={"status": "OLD"})]
    source = _make_source(files, metadata={"a": {"status": "APPROVED", "year": "2020"}})

    result = source.collect_files(["folder1"])

    assert result[0].properties == {"status": "APPROVED", "year": "2020"}


def test_firestore_mode_falls_back_to_drive_for_missing_documents():
    files = [
        File(id="a", name="Song A", properties={"status": "APPROVED"}),
        File(id="b", name="Song B", properties={"status": "DRAFT"}),
    ]
    source = _make_source(files, metadata={"a": {"status": "FIRESTORE"}})

    result = source.collect_files(["folder1"])

    assert result[0].properties == {"status": "FIRESTORE"}
    assert result[1].properties == {"status": "DRAFT"}


def test_client_filter_is_passed_through_to_drive():
    files = [File(id="a", name="Song A", properties={"specialbooks": "pride"})]
    gdrive = Mock(spec=GoogleDriveClient)
    gdrive.query_drive_files_with_client_filter.return_value = files
    source = SongSheetSource(gdrive)

    client_filter = PropertyFilter(
        key="specialbooks", operator="contains", value="pride"
    )
    source.collect_files(["folder1"], client_filter)

    gdrive.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1"], client_filter, modified_after=None
    )


READY_FILTER = PropertyFilter(key="status", operator="equals", value="READY_TO_PLAY")


def test_firestore_mode_filters_on_firestore_properties():
    # Drive writes are off, so a song readied since has no status on Drive.
    files = [File(id="a", name="Song A", properties={})]
    source = _make_source(files, metadata={"a": {"status": "READY_TO_PLAY"}})

    result = source.collect_files(["folder1"], READY_FILTER)

    assert [f.id for f in result] == ["a"]


def test_firestore_mode_filter_ignores_stale_drive_properties():
    files = [File(id="a", name="Song A", properties={"status": "READY_TO_PLAY"})]
    source = _make_source(files, metadata={"a": {"status": "DRAFT"}})

    assert source.collect_files(["folder1"], READY_FILTER) == []


def test_firestore_mode_fetches_drive_files_unfiltered():
    files = [File(id="a", name="Song A", properties={})]
    source = _make_source(files, metadata={"a": {"status": "READY_TO_PLAY"}})

    source.collect_files(["folder1"], READY_FILTER)

    source._gdrive.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1"], None, modified_after=None
    )
