"""Tests for MetadataWriter implementations."""

from unittest.mock import MagicMock, Mock

import pytest
from google.api_core import exceptions as gcp_exceptions
from googleapiclient.errors import HttpError

from ..worker.models import File
from .metadata import DriveMetadataWriter, GCSMetadataWriter


@pytest.fixture
def mock_drive_service():
    """Create a mock Google Drive service object."""
    return MagicMock()


@pytest.fixture
def mock_cache_bucket():
    """Create a mock GCS bucket object."""
    return MagicMock()


@pytest.fixture
def sample_file():
    """A minimal File fixture for metadata-write tests."""
    return File(id="file123", name="test.pdf")


# ---------------------------------------------------------------------------
# DriveMetadataWriter
# ---------------------------------------------------------------------------


def test_drive_writer_calls_files_update(mock_drive_service, sample_file):
    """DriveMetadataWriter should call drive.files().update() with the properties."""
    writer = DriveMetadataWriter(mock_drive_service)
    writer.write(sample_file, {"status": "APPROVED", "artist": "Oasis"})

    mock_drive_service.files.return_value.update.assert_called_once_with(
        fileId="file123",
        body={"properties": {"status": "APPROVED", "artist": "Oasis"}},
        fields="properties",
    )


def test_drive_writer_propagates_api_errors(mock_drive_service, sample_file):
    """DriveMetadataWriter should not swallow Drive API errors."""
    mock_resp = Mock()
    mock_resp.status = 403
    mock_drive_service.files.return_value.update.return_value.execute.side_effect = (
        HttpError(resp=mock_resp, content=b"Forbidden")
    )
    writer = DriveMetadataWriter(mock_drive_service)
    with pytest.raises(HttpError):
        writer.write(sample_file, {"status": "APPROVED"})


# ---------------------------------------------------------------------------
# GCSMetadataWriter
# ---------------------------------------------------------------------------


def test_gcs_writer_writes_properties_without_prefix(mock_cache_bucket, sample_file):
    """GCSMetadataWriter should write properties with no prefix to GCS metadata."""
    mock_blob = MagicMock()
    mock_blob.metadata = {}
    mock_cache_bucket.blob.return_value = mock_blob

    writer = GCSMetadataWriter(mock_cache_bucket)
    writer.write(sample_file, {"status": "APPROVED", "artist": "Oasis"})

    mock_cache_bucket.blob.assert_called_once_with("song-sheets/file123.pdf")
    mock_blob.reload.assert_called_once()
    mock_blob.patch.assert_called_once()

    # Keys must NOT have a prefix
    assert mock_blob.metadata.get("status") == "APPROVED"
    assert mock_blob.metadata.get("artist") == "Oasis"
    assert "tag-status" not in mock_blob.metadata


def test_gcs_writer_preserves_existing_infrastructure_metadata(
    mock_cache_bucket, sample_file
):
    """Existing GCS metadata (e.g. gdrive-file-id) must not be overwritten."""
    mock_blob = MagicMock()
    mock_blob.metadata = {
        "gdrive-file-id": "file123",
        "gdrive-file-name": "Test Song.pdf",
    }
    mock_cache_bucket.blob.return_value = mock_blob

    writer = GCSMetadataWriter(mock_cache_bucket)
    writer.write(sample_file, {"status": "APPROVED"})

    assert mock_blob.metadata["gdrive-file-id"] == "file123"
    assert mock_blob.metadata["gdrive-file-name"] == "Test Song.pdf"
    assert mock_blob.metadata["status"] == "APPROVED"


def test_gcs_writer_blob_not_found_does_not_raise(mock_cache_bucket, sample_file):
    """A missing GCS blob should be silently skipped."""
    mock_blob = MagicMock()
    mock_blob.reload.side_effect = gcp_exceptions.NotFound("not found")
    mock_cache_bucket.blob.return_value = mock_blob

    writer = GCSMetadataWriter(mock_cache_bucket)
    writer.write(sample_file, {"status": "APPROVED"})  # should not raise

    mock_blob.patch.assert_not_called()


def test_gcs_writer_api_error_on_reload_does_not_raise(mock_cache_bucket, sample_file):
    """A GCS API error during blob.reload() should be logged but not re-raised."""
    mock_blob = MagicMock()
    mock_blob.reload.side_effect = gcp_exceptions.GoogleAPICallError("gcs error")
    mock_cache_bucket.blob.return_value = mock_blob

    writer = GCSMetadataWriter(mock_cache_bucket)
    writer.write(sample_file, {"status": "APPROVED"})  # should not raise

    mock_blob.patch.assert_not_called()


def test_gcs_writer_api_error_on_patch_does_not_raise(mock_cache_bucket, sample_file):
    """A GCS API error during blob.patch() should be logged but not re-raised."""
    mock_blob = MagicMock()
    mock_blob.metadata = {}
    mock_blob.patch.side_effect = gcp_exceptions.GoogleAPICallError("gcs patch error")
    mock_cache_bucket.blob.return_value = mock_blob

    writer = GCSMetadataWriter(mock_cache_bucket)
    writer.write(sample_file, {"status": "APPROVED"})  # should not raise


def test_gcs_writer_unchanged_metadata_skips_patch(mock_cache_bucket, sample_file):
    """When GCS metadata already matches, no patch should be issued."""
    mock_blob = MagicMock()
    mock_blob.metadata = {"status": "APPROVED"}
    mock_cache_bucket.blob.return_value = mock_blob

    writer = GCSMetadataWriter(mock_cache_bucket)
    writer.write(sample_file, {"status": "APPROVED"})

    mock_blob.patch.assert_not_called()
