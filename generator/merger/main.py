import os
import tempfile
from functools import lru_cache
from typing import Optional
import PyPDF2
from google.api_core import exceptions as gcp_exceptions
import fitz
import traceback
import shutil
from datetime import datetime
import click


from google.auth import default
from googleapiclient.discovery import build

from google.cloud import storage
from cloudevents.http import CloudEvent


from . import sync
from ..common.config import get_settings
from ..worker.gcp import get_credentials

# Initialize tracing
from ..common.tracing import get_tracer, setup_tracing


@lru_cache(maxsize=1)
def _get_services():
    """Initializes and returns services, using a cache for warm starts."""
    settings = get_settings()

    # Determine project ID from default credentials
    _, project_id = default()
    if project_id:
        os.environ["GCP_PROJECT_ID"] = project_id
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

    credential_config = settings.google_cloud.credentials.get("songbook-merger")
    if not credential_config:
        raise click.Abort("Credential config 'songbook-merger' not found.")

    creds = get_credentials(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )

    service_name = os.environ.get("K_SERVICE", "songbook-generator-merger")
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    gcs_worker_cache_bucket = settings.caching.gcs.worker_cache_bucket

    storage_client = storage.Client(project=project_id)
    cache_bucket = storage_client.bucket(gcs_worker_cache_bucket)

    drive_service = build("drive", "v3", credentials=creds)

    return {
        "tracer": tracer,
        "cache_bucket": cache_bucket,
        "drive": drive_service,
    }


def _fetch_pdf_blobs(services):
    """Fetch all song sheet PDF blobs from GCS cache bucket."""
    with services["tracer"].start_as_current_span("list_blobs") as span:
        prefix = "song-sheets/"
        blobs = list(services["cache_bucket"].list_blobs(prefix=prefix))
        pdf_blobs = [blob for blob in blobs if blob.name.endswith(".pdf")]
        span.set_attribute("total_blobs", len(blobs))
        span.set_attribute("pdf_blobs", len(pdf_blobs))
        return pdf_blobs


def _download_blobs(pdf_blobs, temp_dir, services):
    """Download PDF blobs to a temporary directory and extract metadata."""
    with services["tracer"].start_as_current_span("download_files") as span:
        file_metadata = []
        for blob in pdf_blobs:
            filename = blob.name.replace("/", "_")
            local_path = os.path.join(temp_dir, filename)
            click.echo(f"Downloading {blob.name} to {filename}")
            with services["tracer"].start_as_current_span("download_file") as dl_span:
                dl_span.set_attribute("blob_name", blob.name)
                dl_span.set_attribute("local_path", local_path)
                blob.download_to_filename(local_path)
            blob_metadata = blob.metadata or {}
            song_name = blob_metadata.get("gdrive-file-name", "Unknown Song")
            file_metadata.append({"path": local_path, "name": song_name})
        span.set_attribute("downloaded_count", len(file_metadata))
        return file_metadata


def _merge_pdfs_with_toc(file_metadata, temp_dir, services):
    """Merge PDFs and generate TOC entries."""
    with services["tracer"].start_as_current_span("merge_pdfs") as span:
        click.echo(f"Merging {len(file_metadata)} PDF files...")
        merger = PyPDF2.PdfMerger()
        toc_entries = []
        current_page = 0
        for file_info in file_metadata:
            with open(file_info["path"], "rb") as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                page_count = len(pdf_reader.pages)
            toc_entries.append([1, file_info["name"], current_page + 1])
            current_page += page_count
            merger.append(file_info["path"])
        temp_merged_path = os.path.join(temp_dir, "merged.pdf")
        merger.write(temp_merged_path)
        merger.close()
        span.set_attribute("temp_merged_path", temp_merged_path)
        span.set_attribute("merged_files", len(file_metadata))
        span.set_attribute("toc_entries", len(toc_entries))
        click.echo(f"Successfully created merged PDF: {temp_merged_path}")
        return temp_merged_path, toc_entries


def _add_toc_to_pdf(temp_merged_path, toc_entries, temp_dir, services):
    """Add a table of contents to the merged PDF."""
    with services["tracer"].start_as_current_span("add_toc") as span:
        click.echo("Adding table of contents to merged PDF...")
        doc = fitz.open(temp_merged_path)
        doc.set_toc(toc_entries)
        temp_with_toc_path = os.path.join(temp_dir, "with_toc.pdf")
        doc.save(temp_with_toc_path)
        doc.close()
        span.set_attribute("toc_entries_added", len(toc_entries))
        span.set_attribute("temp_with_toc_path", temp_with_toc_path)
        click.echo(f"Added {len(toc_entries)} entries to table of contents")
        return temp_with_toc_path


def _get_last_merge_time(cache_bucket, tracer_span=None) -> Optional[datetime]:
    """Get the modification time of the last merged PDF from cache."""
    try:
        blob = cache_bucket.get_blob("merged-pdf/latest.pdf")
        if not blob:
            return None

        last_merge_time = blob.updated
        if last_merge_time:
            click.echo(
                f"Last merge was at {last_merge_time}. Syncing changes since then."
            )
            if tracer_span:
                tracer_span.set_attribute("last_merge_time", str(last_merge_time))
        return last_merge_time
    except gcp_exceptions.NotFound:
        click.echo("No previous merged PDF found. Performing a full sync.")
        if tracer_span:
            tracer_span.set_attribute("last_merge_time", "None")
        return None


def _upload_to_cache(file_path, services):
    """Upload the final merged PDF to the GCS cache."""
    with services["tracer"].start_as_current_span("upload_to_cache") as span:
        cache_blob_name = "merged-pdf/latest.pdf"
        cache_blob = services["cache_bucket"].blob(cache_blob_name)
        click.echo(f"Uploading merged PDF to cache at: {cache_blob_name}")
        cache_blob.upload_from_filename(file_path, content_type="application/pdf")
        span.set_attribute("cache_blob_name", cache_blob_name)


def fetch_and_merge_pdfs(output_path, services):
    """
    Fetch all song sheet PDFs from GCS cache bucket and merge them into a single PDF.

    Args:
        output_path: Path where the merged PDF should be saved.
        services: A dictionary containing initialized clients (tracer, cache_bucket).

    Returns:
        str: Path to the merged PDF file (same as output_path)
    """
    with services["tracer"].start_as_current_span("fetch_and_merge_pdfs") as span:
        pdf_blobs = _fetch_pdf_blobs(services)
        span.set_attribute("pdf_count", len(pdf_blobs))
        if not pdf_blobs:
            click.echo("No PDF files found in the cache bucket")
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            span.set_attribute("temp_dir", temp_dir)
            file_metadata = _download_blobs(pdf_blobs, temp_dir, services)
            file_metadata.sort(key=lambda x: x["name"])

            temp_merged_path, toc_entries = _merge_pdfs_with_toc(
                file_metadata, temp_dir, services
            )

            temp_with_toc_path = _add_toc_to_pdf(
                temp_merged_path, toc_entries, temp_dir, services
            )

            _upload_to_cache(temp_with_toc_path, services)

            click.echo(f"Copying merged PDF with TOC to: {output_path}")
            shutil.copy2(temp_with_toc_path, output_path)
            span.set_attribute("final_output_path", output_path)

            return output_path


def merger_main(cloud_event: CloudEvent):
    """
    Cloud Function triggered by a CloudEvent to sync and merge PDFs.

    This function is designed to be triggered by a Pub/Sub message.

    Args:
        cloud_event (CloudEvent): The CloudEvent representing the trigger.
          The `data` payload is ignored, but `attributes` are used.
    """
    services = _get_services()
    with services["tracer"].start_as_current_span("merger_main") as main_span:
        try:
            attributes = cloud_event.get_attributes() or {}
            # The 'force' attribute will be a string 'true' or 'false'.
            force_sync = attributes.get("force", "false").lower() == "true"

            source_folders = get_settings().song_sheets.folder_ids

            if not source_folders:
                click.echo("Error: No source folders specified.", err=True)
                main_span.set_attribute("status", "failed_no_source_folders")
                raise ValueError("No source folders specified in configuration.")

            # Add source_folders to span attributes for tracing
            main_span.set_attribute("source_folders", ",".join(source_folders))
            main_span.set_attribute("force_sync", str(force_sync))

            # Get the modification time of the last merged PDF to use as a cutoff
            last_merge_time = None
            if not force_sync:
                last_merge_time = _get_last_merge_time(
                    services["cache_bucket"], main_span
                )
            else:
                click.echo("Force flag set. Performing a full sync.")
                main_span.set_attribute("last_merge_time", "None (forced)")

            with services["tracer"].start_as_current_span(
                "sync_operation"
            ) as sync_span:
                click.echo(f"Syncing folders: {source_folders}")
                # Sync files and their metadata before merging.
                synced_files_count = sync.sync_cache(
                    source_folders,
                    services,
                    modified_after=last_merge_time,
                    update_tags=True,  # Always update tags
                )
                sync_span.set_attribute("synced_files_count", synced_files_count)
                click.echo("Sync complete.")

            if not force_sync and synced_files_count == 0:
                click.echo("No files were updated since the last merge. Nothing to do.")
                main_span.set_attribute("status", "skipped_no_changes")
                return

            click.echo("Starting PDF merge operation")

            # Create a temporary file for the merged PDF
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_output_path = temp_file.name

            try:
                # Fetch and merge PDFs
                with services["tracer"].start_as_current_span(
                    "merge_operation"
                ) as merge_span:
                    result_path = fetch_and_merge_pdfs(temp_output_path, services)

                    if not result_path:
                        main_span.set_attribute("status", "no_files")
                        click.echo("No PDF files found to merge.")
                        return

                    merge_span.set_attribute("merged_pdf_path", result_path)
                    main_span.set_attribute("status", "success")

            finally:
                # Clean up the temporary file
                if os.path.exists(temp_output_path):
                    os.unlink(temp_output_path)

        except Exception:  # noqa: BLE001 - Top level error handler
            main_span.set_attribute("status", "failed")

            click.echo("Merge operation failed.", err=True)
            click.echo("Error details:", err=True)
            exc_info = traceback.format_exc()
            click.echo(exc_info, err=True)
            main_span.set_attribute("error.stack_trace", exc_info)

            # Re-raise to ensure the function invocation is marked as a failure.
            # The framework will handle this and return a 500-level response.
            raise
