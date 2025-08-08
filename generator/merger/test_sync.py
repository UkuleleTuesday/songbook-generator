from unittest.mock import MagicMock, patch

import pytest

from ..worker.models import File
from .sync import sync_cache


@pytest.fixture
def mock_services():
    """Provides a mock services dictionary."""
    services = {
        "tracer": MagicMock(),
        "drive": MagicMock(),
        "cache_bucket": MagicMock(),
        "tagger": MagicMock(),
    }
    services[
        "tracer"
    ].start_as_current_span.return_value.__enter__.return_value = MagicMock()
    return services


@patch("generator.merger.sync.Tagger")
@patch("generator.merger.sync.GoogleDriveClient")
@patch("generator.merger.sync._get_files_to_update")
@patch("generator.merger.sync.init_cache")
@patch("generator.merger.sync._sync_gcs_metadata_from_drive")
def test_sync_cache_calls_sync_metadata_correctly(
    mock_sync_metadata,
    mock_init_cache,
    mock_get_files,
    mock_gdrive_client,
    mock_tagger,
    mock_services,
):
    """
    Verify that sync_cache calls _sync_gcs_metadata_from_drive with the correct arguments.
    """
    # Arrange
    mock_file = File(id="test_id", name="test_name")
    mock_get_files.return_value = [mock_file]
    mock_cache_instance = mock_init_cache.return_value

    # Act
    sync_cache(
        source_folders=["folder1"],
        services=mock_services,
        with_metadata=True,
        update_tags_only=False,
    )

    # Assert
    mock_sync_metadata.assert_called_once_with(
        ["folder1"],
        mock_cache_instance,
        mock_services["drive"],
        mock_services["cache_bucket"],
        mock_services["tracer"],
    )


@patch("generator.merger.sync.Tagger")
@patch("generator.merger.sync.GoogleDriveClient")
@patch("generator.merger.sync._get_files_to_update")
@patch("generator.merger.sync.init_cache")
@patch("generator.merger.sync._sync_gcs_metadata_from_drive")
def test_sync_cache_download_file_stream_args(
    mock_sync_metadata,
    mock_init_cache,
    mock_get_files,
    mock_gdrive_client,
    mock_tagger,
    mock_services,
):
    """
    Verify that sync_cache calls download_file_stream without the legacy 'subset_fonts' argument.
    """
    # Arrange
    mock_file = File(id="test_id", name="test_name")
    mock_get_files.return_value = [mock_file]
    mock_gdrive_instance = mock_gdrive_client.return_value

    # Act
    sync_cache(
        source_folders=["folder1"],
        services=mock_services,
        modified_after=None,
    )

    # Assert
    mock_gdrive_instance.download_file_stream.assert_called_once_with(
        mock_file, use_cache=False
    )
