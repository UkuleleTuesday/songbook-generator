import os
from typing import List, Optional
from datetime import datetime
import click
from google.api_core import exceptions as gcp_exceptions

from ..common.caching import init_cache
from ..common.gdrive import GoogleDriveClient
from ..worker.models import File


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
    modified_after: Optional[datetime] = None,
) -> int:
    """
    Ensure that files in the given drive source folders are synced into the GCS cache.
    Returns the number of files synced.
    """
    with services["tracer"].start_as_current_span("sync_cache") as span:
        span.set_attribute("source_folders_count", len(source_folders))
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
                # Download file without using cache to get fresh content
                file_stream = gdrive_client.download_file_stream(file, use_cache=False)

                # Explicitly write to cache with metadata
                cache_key = f"song-sheets/{file.id}.pdf"
                metadata = {
                    "gdrive-file-id": file.id,
                    "gdrive-file-name": file.name,
                }
                cache.put(cache_key, file_stream.read(), metadata=metadata)
                click.echo(f"  Stored {cache_key} in cache with metadata.")

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
                # remove .pdf extension before adding .metadata.json
                base_key = os.path.splitext(blob.name)[0]
                click.echo(f"  ... saving metadata for {blob.name}")
                local_cache.put_metadata(base_key, blob.metadata)

        click.echo("Download complete.")
