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
    gdrive.query_drive_files_with_client_filter.return_value = files

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

    client_filter = PropertyFilter(key="specialbooks", operator="contains", value="pride")
    source.collect_files(["folder1"], client_filter)

    gdrive.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1"], client_filter
    )
