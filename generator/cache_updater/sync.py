import os
from typing import List, Optional
from datetime import datetime
import click
from google.api_core import exceptions as gcp_exceptions

from ..common.caching import init_cache
from ..common.gdrive import GoogleDriveClient
from ..worker.models import File

_SONGS_SUBFOLDER_NAME = "Songs"


def _sync_gcs_metadata_from_drive(
    source_folders: List[str], cache, drive_service, cache_bucket, tracer
):
    """Sync GCS cache metadata with Google Drive file information."""
    with tracer.start_as_current_span("_sync_gcs_metadata_from_drive") as span:
        click.echo("Starting metadata sync from Drive to GCS cache...")
        gdrive_client = GoogleDriveClient(cache=cache, drive=drive_service)
        all_drive_files = gdrive_client.query_drive_files(source_folders)
        drive_file_map = {file.id: file for file in all_drive_files}
        span.set_attribute("drive_files_found", len(all_drive_files))

        prefix = "song-sheets/"
        cached_blobs = list(cache_bucket.list_blobs(prefix=prefix))
        span.set_attribute("cached_blobs_found", len(cached_blobs))

        updated_count, skipped_count, error_count = 0, 0, 0
        for blob in cached_blobs:
            filename = blob.name[len(prefix) :]
            drive_file_id = os.path.splitext(filename)[0]

            if drive_file_id not in drive_file_map:
                skipped_count += 1
                continue

            drive_file = drive_file_map[drive_file_id]
            expected_name = drive_file.name
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
                click.echo(f"  UPDATE: {blob.name} metadata updated.")
                updated_count += 1
            except gcp_exceptions.GoogleAPICallError as e:
                click.echo(f"  ERROR: Failed to update {blob.name}: {e}", err=True)
                error_count += 1
        click.echo(
            f"Metadata sync summary: {updated_count} updated, {skipped_count} skipped, {error_count} errors."
        )


def _get_files_to_update(
    drive_service,
    source_folders: List[str],
    modified_after: Optional[datetime] = None,
) -> List[File]:
    """
    Query Google Drive for files in given folders modified after a certain time.
    """
    gdrive_client = GoogleDriveClient(cache=init_cache(), drive=drive_service)
    return gdrive_client.query_drive_files(
        source_folders, modified_after=modified_after
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

        cache = init_cache()

        files_to_update = _get_files_to_update(
            services["drive"], source_folders, modified_after
        )

        span.set_attribute("total_files_found", len(files_to_update))
        if modified_after:
            span.set_attribute(
                "files_to_update",
                ", ".join([f.name for f in files_to_update]) or "None",
            )
        else:
            span.set_attribute("files_to_update", "all")

        if not files_to_update:
            click.echo("No new or modified files to sync.")
            return 0

        gdrive_client = GoogleDriveClient(cache=cache, drive=services["drive"])
        for file in files_to_update:
            with services["tracer"].start_as_current_span("sync_file"):
                click.echo(f"Syncing {file.name} (ID: {file.id})")
                gdrive_client.download_file_stream(
                    file,
                    use_cache=True,
                )

        if with_metadata:
            _sync_gcs_metadata_from_drive(
                source_folders,
                cache,
                services["drive"],
                services["cache_bucket"],
                services["tracer"],
            )

        return len(files_to_update)


def download_gcs_cache_to_local(
    services, local_cache_dir: str, with_metadata: bool = False
):
    """
    Downloads all files from the GCS cache bucket to a local directory.
    If with_metadata is True, also saves blob metadata to a JSON file.
    """
    with services["tracer"].start_as_current_span(
        "download_gcs_cache_to_local"
    ) as span:
        from ..common.caching import init_cache

        local_cache = init_cache(use_gcs=False)
        span.set_attribute("local_cache_dir", local_cache_dir)
        span.set_attribute("with_metadata", with_metadata)

        cache_bucket = services["cache_bucket"]
        blobs = list(cache_bucket.list_blobs())
        span.set_attribute("total_blobs_to_download", len(blobs))

        if not blobs:
            click.echo("No files found in GCS cache. Nothing to download.")
            return

        click.echo(f"Found {len(blobs)} files in GCS cache. Starting download...")

        for blob in blobs:
            destination_path = os.path.join(local_cache_dir, blob.name)
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            click.echo(f"Downloading {blob.name} to {destination_path}")
            blob.download_to_filename(destination_path)
            if with_metadata and blob.metadata:
                click.echo(f"  ... saving metadata for {blob.name}")
                local_cache.put_metadata(blob.name, blob.metadata)

        click.echo("Download complete.")


def _sync_gcs_metadata_for_files(files: List[File], cache_bucket, tracer):
    """
    Update GCS blob metadata for a specific list of File objects.

    Unlike _sync_gcs_metadata_from_drive, no Drive query is performed;
    the caller supplies the File objects directly. Does a targeted
    blob.reload() per file ID rather than listing all blobs.
    """
    with tracer.start_as_current_span("_sync_gcs_metadata_for_files") as span:
        click.echo("Syncing GCS metadata for edition files...")
        file_map = {f.id: f for f in files}
        span.set_attribute("files_count", len(file_map))

        prefix = "song-sheets/"
        updated_count, skipped_count, error_count = 0, 0, 0

        for file_id, drive_file in file_map.items():
            blob_name = f"{prefix}{file_id}.pdf"
            blob = cache_bucket.blob(blob_name)
            try:
                blob.reload()
            except gcp_exceptions.NotFound:
                skipped_count += 1
                continue

            expected_name = drive_file.name
            current_metadata = blob.metadata or {}
            if current_metadata.get(
                "gdrive-file-id"
            ) == file_id and current_metadata.get("gdrive-file-name") == str(
                expected_name
            ):
                continue

            new_metadata = dict(current_metadata)
            new_metadata["gdrive-file-id"] = file_id
            new_metadata["gdrive-file-name"] = expected_name
            try:
                blob.metadata = new_metadata
                blob.patch()
                click.echo(f"  UPDATE: {blob_name} metadata updated.")
                updated_count += 1
            except gcp_exceptions.GoogleAPICallError as e:
                click.echo(f"  ERROR: Failed to update {blob_name}: {e}", err=True)
                error_count += 1

        click.echo(
            f"Edition metadata sync: {updated_count} updated, "
            f"{skipped_count} skipped, {error_count} errors."
        )
        span.set_attribute("updated_count", updated_count)
        span.set_attribute("skipped_count", skipped_count)
        span.set_attribute("error_count", error_count)


def sync_cache_for_edition_folder(edition_folder_id: str, services) -> int:
    """
    Prime the GCS cache with all songs from an edition's Songs/ subfolder.

    Resolves shortcuts so that shortcut entries pointing at source-folder
    files are stored under the *real* file ID — matching the key that
    copy_pdfs looks up in the merged PDF index.

    Returns:
        Number of files synced.  0 if the Songs/ subfolder is missing or empty.
    """
    with services["tracer"].start_as_current_span(
        "sync_cache_for_edition_folder"
    ) as span:
        span.set_attribute("edition_folder_id", edition_folder_id)

        cache = init_cache()
        gdrive_client = GoogleDriveClient(cache=cache, drive=services["drive"])

        songs_folder_id = gdrive_client.find_subfolder_by_name(
            edition_folder_id, _SONGS_SUBFOLDER_NAME
        )
        if not songs_folder_id:
            click.echo(
                f"Warning: No '{_SONGS_SUBFOLDER_NAME}' subfolder found in edition "
                f"folder {edition_folder_id}. Nothing to sync.",
                err=True,
            )
            span.set_attribute("songs_subfolder_found", False)
            return 0

        span.set_attribute("songs_subfolder_found", True)
        span.set_attribute("songs_folder_id", songs_folder_id)

        files = gdrive_client.list_folder_contents(
            songs_folder_id, resolve_shortcuts=True
        )
        span.set_attribute("files_found", len(files))

        if not files:
            click.echo(
                f"Warning: '{_SONGS_SUBFOLDER_NAME}' subfolder {songs_folder_id} "
                "is empty. Nothing to sync."
            )
            return 0

        click.echo(
            f"Syncing {len(files)} file(s) from edition "
            f"'{_SONGS_SUBFOLDER_NAME}/' subfolder..."
        )
        for file in files:
            with services["tracer"].start_as_current_span("sync_edition_file"):
                click.echo(f"  Syncing {file.name} (ID: {file.id})")
                gdrive_client.download_file_stream(file, use_cache=True)

        _sync_gcs_metadata_for_files(
            files, services["cache_bucket"], services["tracer"]
        )

        span.set_attribute("synced_count", len(files))
        return len(files)
