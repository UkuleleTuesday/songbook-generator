import os
from typing import List, Optional
from datetime import datetime
from google.api_core import exceptions as gcp_exceptions

from ..common import gdrive


def _sync_gcs_metadata_from_drive(source_folders: List[str], services):
    """Sync GCS cache metadata with Google Drive file information."""
    with services["tracer"].start_as_current_span(
        "_sync_gcs_metadata_from_drive"
    ) as span:
        print("Starting metadata sync from Drive to GCS cache...")
        all_drive_files = []
        for folder_id in source_folders:
            files = gdrive.query_drive_files(services["drive"], folder_id)
            all_drive_files.extend(files)
        drive_file_map = {file["id"]: file for file in all_drive_files}
        span.set_attribute("drive_files_found", len(all_drive_files))

        prefix = "song-sheets/"
        cached_blobs = list(services["cache_bucket"].list_blobs(prefix=prefix))
        span.set_attribute("cached_blobs_found", len(cached_blobs))

        updated_count, skipped_count, error_count = 0, 0, 0
        for blob in cached_blobs:
            filename = blob.name[len(prefix) :]
            drive_file_id = os.path.splitext(filename)[0]

            if drive_file_id not in drive_file_map:
                skipped_count += 1
                continue

            drive_file = drive_file_map[drive_file_id]
            expected_name = drive_file.get("name", "")
            current_metadata = blob.metadata or {}

            if current_metadata.get(
                "gdrive-file-id"
            ) == drive_file_id and current_metadata.get("gdrive-file-name") == str(
                expected_name
            ):
                continue

            new_metadata = dict(current_metadata)
            new_metadata["gdrive-file-id"] = drive_file_id
            new_metadata["gdrive-file-name"] = expected_name
            try:
                blob.metadata = new_metadata
                blob.patch()
                print(f"  UPDATE: {blob.name} metadata updated.")
                updated_count += 1
            except gcp_exceptions.GoogleAPICallError as e:
                print(f"  ERROR: Failed to update {blob.name}: {e}")
                error_count += 1
        print(
            f"Metadata sync summary: {updated_count} updated, {skipped_count} skipped, {error_count} errors."
        )


def sync_cache(
    source_folders: List[str],
    services,
    with_metadata: bool = True,
    modified_after: Optional[datetime] = None,
) -> int:
    """
    Ensure that files in the given drive source folders are synced into the GCS cache.
    Returns the number of files synced.
    """
    with services["tracer"].start_as_current_span("sync_cache") as span:
        span.set_attribute("source_folders_count", len(source_folders))
        span.set_attribute("with_metadata", with_metadata)
        if modified_after:
            span.set_attribute("modified_after", str(modified_after))

        from ..common.caching import init_cache

        cache = init_cache()

        all_files = []
        for folder_id in source_folders:
            files = gdrive.query_drive_files(
                services["drive"], folder_id, modified_after=modified_after
            )
            all_files.extend(files)

        span.set_attribute("total_files_found", len(all_files))

        if not all_files:
            print("No new or modified files to sync.")
            return 0

        for file in all_files:
            with services["tracer"].start_as_current_span("sync_file"):
                print(f"Syncing {file['name']} (ID: {file['id']})")
                gdrive.download_file_stream(services["drive"], file, cache)

        if with_metadata:
            _sync_gcs_metadata_from_drive(source_folders, services)

        return len(all_files)
