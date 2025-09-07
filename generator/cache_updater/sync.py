import os
import json
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
    gdrive_client = GoogleDriveClient(drive=drive_service)
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

        cache = services.get("cache") or init_cache()

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

        gdrive_client = GoogleDriveClient(drive=services["drive"])
        for file in files_to_update:
            with services["tracer"].start_as_current_span("sync_file"):
                click.echo(f"Syncing {file.name} (ID: {file.id})")

                # Store metadata file alongside the PDF
                metadata_key = f"song-sheets/{file.id}.json"
                file_metadata = {
                    "id": file.id,
                    "name": file.name,
                    "properties": file.properties or {},
                    "mimeType": file.mimeType,
                    "parents": file.parents or [],
                }
                cache.put(
                    metadata_key,
                    json.dumps(file_metadata, indent=2).encode("utf-8"),
                )
                click.echo(f"  Stored metadata for {file.name} at {metadata_key}")

                # Download file without using cache to get fresh content
                file_stream = gdrive_client.download_file_stream(file)

                # Explicitly write to cache with metadata
                pdf_cache_key = f"song-sheets/{file.id}.pdf"
                gcs_metadata = {
                    "gdrive-file-id": file.id,
                    "gdrive-file-name": file.name,
                }
                cache.put(pdf_cache_key, file_stream.read(), metadata=gcs_metadata)
                click.echo(f"  Stored {pdf_cache_key} in cache with GCS metadata.")

        return len(files_to_update)


