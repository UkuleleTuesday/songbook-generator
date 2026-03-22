"""Song metadata writers.

This module provides an abstraction for writing computed song metadata
to different storage backends (Google Drive or Google Cloud Storage).
The destination is controlled by ``settings.tags.metadata_destination``
(env var ``TAGS_METADATA_DESTINATION``) or by the ``--destination`` flag
on the CLI ``tags update`` command.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import storage as gcs_storage
from loguru import logger

from ..worker.models import File

GCS_SONG_SHEETS_PREFIX = "song-sheets/"


class MetadataWriter(ABC):
    """Abstract base class for writing computed song metadata to a destination."""

    @abstractmethod
    def write(self, file: File, properties: Dict[str, str]) -> None:
        """Write ``properties`` for ``file``.

        Args:
            file: The Drive file whose metadata should be updated.
            properties: Mapping of property name to string value.
        """


class DriveMetadataWriter(MetadataWriter):
    """Writes song metadata as Google Drive custom file properties."""

    def __init__(self, drive_service: Any) -> None:
        """
        Args:
            drive_service: An authenticated Google Drive API service resource.
        """
        self.drive_service = drive_service

    def write(self, file: File, properties: Dict[str, str]) -> None:
        """Write ``properties`` to the Google Drive file's custom properties.

        Args:
            file: The Drive file to update.
            properties: Mapping of property name to string value.
        """
        self.drive_service.files().update(
            fileId=file.id,
            body={"properties": properties},
            fields="properties",
        ).execute()


class GCSMetadataWriter(MetadataWriter):
    """Writes song metadata to GCS blob metadata for the cached song sheet.

    Properties are stored directly under their tag names (no prefix), so
    they sit alongside infrastructure fields such as ``gdrive-file-id`` and
    ``gdrive-file-name``.  Errors are logged but never propagated, so a GCS
    failure never blocks other operations.
    """

    def __init__(self, cache_bucket: Any) -> None:
        """
        Args:
            cache_bucket: A ``google.cloud.storage.Bucket`` for the GCS worker
                cache, used to look up and patch the cached PDF blob.
        """
        self.cache_bucket = cache_bucket

    def write(self, file: File, properties: Dict[str, str]) -> None:
        """Write ``properties`` to GCS blob metadata for the cached song sheet.

        Existing GCS metadata keys (e.g. ``gdrive-file-id``) are preserved;
        only the keys present in ``properties`` are added or updated.

        Args:
            file: The Drive file whose cached GCS blob will be updated.
            properties: Mapping of property name to string value.
        """
        blob_name = f"{GCS_SONG_SHEETS_PREFIX}{file.id}.pdf"
        blob = self.cache_bucket.blob(blob_name)
        try:
            blob.reload()
        except gcp_exceptions.NotFound:
            logger.warning(
                "GCS blob {} not found, skipping GCS metadata write.", blob_name
            )
            return
        except gcp_exceptions.GoogleAPICallError as e:
            logger.warning("Failed to read GCS metadata for {}: {}", blob_name, e)
            return

        current_metadata = blob.metadata or {}
        new_metadata = dict(current_metadata)
        new_metadata.update(properties)

        if new_metadata == current_metadata:
            logger.debug("GCS metadata unchanged for {}.", blob_name)
            return

        try:
            blob.metadata = new_metadata
            blob.patch()
            logger.info("GCS metadata updated for {}.", blob_name)
        except gcp_exceptions.GoogleAPICallError as e:
            logger.warning("Failed to update GCS metadata for {}: {}", blob_name, e)


def build_metadata_writer(
    destination: str,
    drive_service: Any = None,
    gcs_bucket_name: Optional[str] = None,
    gcs_project_id: Optional[str] = None,
) -> MetadataWriter:
    """Build and return the appropriate ``MetadataWriter`` for ``destination``.

    Args:
        destination: Either ``'drive'`` or ``'gcs'``.
        drive_service: Authenticated Drive API service resource; required when
            ``destination`` is ``'drive'``.
        gcs_bucket_name: GCS bucket name; required when ``destination`` is
            ``'gcs'``.
        gcs_project_id: Optional GCP project ID used when creating the GCS
            client for the ``'gcs'`` destination.

    Returns:
        A :class:`MetadataWriter` instance for the requested destination.

    Raises:
        ValueError: If ``destination`` is unknown, or a required argument for
            the requested destination is missing.
    """
    dest = destination.lower()
    if dest == "drive":
        if drive_service is None:
            raise ValueError(
                "drive_service is required for the 'drive' metadata destination."
            )
        return DriveMetadataWriter(drive_service)
    if dest == "gcs":
        if not gcs_bucket_name:
            raise ValueError(
                "gcs_bucket_name is required for the 'gcs' metadata destination."
            )
        storage_client = gcs_storage.Client(project=gcs_project_id)
        cache_bucket = storage_client.bucket(gcs_bucket_name)
        return GCSMetadataWriter(cache_bucket)
    raise ValueError(
        f"Unknown metadata destination '{destination}'. Must be 'drive' or 'gcs'."
    )
