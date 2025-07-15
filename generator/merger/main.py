import os
import tempfile
import PyPDF2
import fitz
from google.cloud import storage
import traceback
import shutil
from typing import List

import os
import tempfile
import PyPDF2
import fitz
from google.cloud import storage
import traceback
import shutil
from typing import List

from google.auth import default
from googleapiclient.discovery import build

from . import sync
from ..common import gdrive
from ..common.config import load_config_folder_ids

# Initialize tracing
from ..common.tracing import get_tracer, setup_tracing

# Cache for initialized clients to avoid re-initialization on warm starts
_services = None


def _get_services():
    """Initializes and returns services, using a cache for warm starts."""
    global _services
    if _services is not None:
        return _services

    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    service_name = os.environ.get("K_SERVICE", "songbook-generator-merger")
    os.environ["GCP_PROJECT_ID"] = project_id
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    gcs_worker_cache_bucket = os.environ["GCS_WORKER_CACHE_BUCKET"]
    storage_client = storage.Client(project=project_id)
    cache_bucket = storage_client.bucket(gcs_worker_cache_bucket)

    creds, _ = default(
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    drive_service = build("drive", "v3", credentials=creds)

    _services = {
        "tracer": tracer,
        "cache_bucket": cache_bucket,
        "drive": drive_service,
    }
    return _services


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
            print(f"Downloading {blob.name} to {filename}")
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
        print(f"Merging {len(file_metadata)} PDF files...")
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
        print(f"Successfully created merged PDF: {temp_merged_path}")
        return temp_merged_path, toc_entries


def _add_toc_to_pdf(temp_merged_path, toc_entries, temp_dir, services):
    """Add a table of contents to the merged PDF."""
    with services["tracer"].start_as_current_span("add_toc") as span:
        print("Adding table of contents to merged PDF...")
        doc = fitz.open(temp_merged_path)
        doc.set_toc(toc_entries)
        temp_with_toc_path = os.path.join(temp_dir, "with_toc.pdf")
        doc.save(temp_with_toc_path)
        doc.close()
        span.set_attribute("toc_entries_added", len(toc_entries))
        span.set_attribute("temp_with_toc_path", temp_with_toc_path)
        print(f"Added {len(toc_entries)} entries to table of contents")
        return temp_with_toc_path


def _upload_to_cache(file_path, services):
    """Upload the final merged PDF to the GCS cache."""
    with services["tracer"].start_as_current_span("upload_to_cache") as span:
        cache_blob_name = "merged-pdf/latest.pdf"
        cache_blob = services["cache_bucket"].blob(cache_blob_name)
        print(f"Uploading merged PDF to cache at: {cache_blob_name}")
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
            print("No PDF files found in the cache bucket")
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

            print(f"Copying merged PDF with TOC to: {output_path}")
            shutil.copy2(temp_with_toc_path, output_path)
            span.set_attribute("final_output_path", output_path)

            return output_path


def merger_main(request):
    """HTTP Cloud Function for syncing and merging PDFs from GCS cache."""
    services = _get_services()
    with services["tracer"].start_as_current_span("merger_main") as main_span:
        try:
            # Get source folders from request payload, or fall back to config
            request_json = request.get_json(silent=True)
            source_folders = (
                request_json.get("source_folders")
                if request_json
                else load_config_folder_ids()
            )
            if not source_folders:
                source_folders = load_config_folder_ids()

            main_span.set_attribute(
                "source_folders", ",".join(source_folders) if source_folders else ""
            )
            with services["tracer"].start_as_current_span("sync_operation"):
                print(f"Syncing folders: {source_folders}")
                # Sync files and their metadata before merging.
                sync.sync_cache(source_folders, services)
                print("Sync complete.")

            print("Starting PDF merge operation")

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
                        return {"error": "No PDF files found to merge"}, 404

                    merge_span.set_attribute("merged_pdf_path", result_path)

                # Read the merged PDF data
                with services["tracer"].start_as_current_span(
                    "return_pdf"
                ) as return_span:
                    with open(result_path, "rb") as pdf_file:
                        pdf_data = pdf_file.read()

                    return_span.set_attribute("pdf_size_bytes", len(pdf_data))
                    main_span.set_attribute("status", "success")

                    return (
                        pdf_data,
                        200,
                        {
                            "Content-Type": "application/pdf",
                            "Content-Disposition": 'attachment; filename="merged-songbook.pdf"',
                        },
                    )

            finally:
                # Clean up the temporary file
                if os.path.exists(temp_output_path):
                    os.unlink(temp_output_path)

        except Exception as e:
            main_span.set_attribute("error", str(e))
            main_span.set_attribute("status", "failed")

            print(f"Merge operation failed: {str(e)}")
            print("Error details:")
            print(traceback.format_exc())

            return {"error": f"Internal error during PDF merge: {str(e)}"}, 500
