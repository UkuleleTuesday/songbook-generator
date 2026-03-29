import os
import tempfile
from unittest.mock import Mock
import fitz
import pytest
from cloudevents.http import CloudEvent

from generator.cache_updater.main import (
    _download_blobs,
    _merge_pdfs_with_toc,
    _parse_cloud_event,
)


@pytest.fixture
def mock_cloud_event():
    """Fixture to create a mock CloudEvent."""

    def _create_event(attributes=None, data=None):
        if data is None:
            data = {"message": {"attributes": attributes or {}}}
        event = Mock(spec=CloudEvent)
        event.get_attributes.return_value = {}  # Mock top-level attributes
        event.get_data.return_value = data
        return event

    return _create_event


def test_parse_cloud_event_force_sync_true(mock_cloud_event):
    """Test parsing with 'force' attribute set to 'true'."""
    event = mock_cloud_event(attributes={"force": "true"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is True


def test_parse_cloud_event_force_sync_false(mock_cloud_event):
    """Test parsing with 'force' attribute set to 'false'."""
    event = mock_cloud_event(attributes={"force": "false"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


def test_parse_cloud_event_force_sync_case_insensitive(mock_cloud_event):
    """Test that 'force' attribute parsing is case-insensitive."""
    event = mock_cloud_event(attributes={"force": "True"})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is True


def test_parse_cloud_event_no_force_attribute(mock_cloud_event):
    """Test parsing when 'force' attribute is missing."""
    event = mock_cloud_event(attributes={})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


def test_parse_cloud_event_no_attributes(mock_cloud_event):
    """Test parsing when the message has no 'attributes' key."""
    event = mock_cloud_event(attributes=None)
    event.get_data.return_value = {"message": {}}
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


def test_parse_cloud_event_no_message(mock_cloud_event):
    """Test parsing when the data has no 'message' key."""
    event = mock_cloud_event(data={})
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False


# ---------------------------------------------------------------------------
# _download_blobs – file ID extraction
# ---------------------------------------------------------------------------


def _make_blob(name, metadata=None):
    blob = Mock()
    blob.name = name
    blob.metadata = metadata or {}
    blob.download_to_filename = Mock()
    return blob


def test_download_blobs_extracts_file_id_from_blob_name(tmp_path):
    """File ID is extracted from the blob name (song-sheets/{id}.pdf)."""
    tracer = Mock()
    tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=Mock())
    tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=False)
    services = {"tracer": tracer}

    blob = _make_blob(
        "song-sheets/abc123.pdf",
        metadata={"gdrive-file-name": "Amazing Grace"},
    )

    result = _download_blobs([blob], str(tmp_path), services)

    assert len(result) == 1
    assert result[0]["id"] == "abc123"
    assert result[0]["name"] == "Amazing Grace"


def test_download_blobs_extracts_id_for_multiple_files(tmp_path):
    tracer = Mock()
    tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=Mock())
    tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=False)
    services = {"tracer": tracer}

    blobs = [
        _make_blob("song-sheets/id1.pdf", metadata={"gdrive-file-name": "Song A"}),
        _make_blob("song-sheets/id2.pdf", metadata={"gdrive-file-name": "Song B"}),
    ]

    result = _download_blobs(blobs, str(tmp_path), services)

    ids = [r["id"] for r in result]
    assert ids == ["id1", "id2"]


# ---------------------------------------------------------------------------
# _merge_pdfs_with_toc – TOC entries use file IDs
# ---------------------------------------------------------------------------


def _write_single_page_pdf(path):
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def test_merge_pdfs_with_toc_uses_file_id_as_toc_title(tmp_path):
    """TOC entry titles must be file IDs, not file names."""
    tracer = Mock()
    tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=Mock())
    tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=False)
    services = {"tracer": tracer}

    pdf_path = str(tmp_path / "song.pdf")
    _write_single_page_pdf(pdf_path)

    file_metadata = [{"path": pdf_path, "name": "Amazing Grace", "id": "abc123"}]

    merged_path, toc_entries = _merge_pdfs_with_toc(file_metadata, str(tmp_path), services)

    assert len(toc_entries) == 1
    assert toc_entries[0][1] == "abc123"   # title is the file ID
    assert toc_entries[0][1] != "Amazing Grace"


def test_merge_pdfs_with_toc_different_ids_same_name(tmp_path):
    """Two files with the same name but different IDs produce distinct TOC entries."""
    tracer = Mock()
    tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=Mock())
    tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=False)
    services = {"tracer": tracer}

    pdf1 = str(tmp_path / "a.pdf")
    pdf2 = str(tmp_path / "b.pdf")
    _write_single_page_pdf(pdf1)
    _write_single_page_pdf(pdf2)

    file_metadata = [
        {"path": pdf1, "name": "Same Song", "id": "original_id"},
        {"path": pdf2, "name": "Same Song", "id": "custom_id"},
    ]

    _, toc_entries = _merge_pdfs_with_toc(file_metadata, str(tmp_path), services)

    titles = [e[1] for e in toc_entries]
    assert titles == ["original_id", "custom_id"]


def test_parse_cloud_event_no_data(mock_cloud_event):
    """Test parsing when the CloudEvent has no data payload."""
    event = mock_cloud_event(data=None)
    result = _parse_cloud_event(event)
    assert result["force_sync"] is False
