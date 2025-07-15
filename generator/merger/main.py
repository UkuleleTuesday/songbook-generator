import os
import tempfile
import PyPDF2
import fitz
from google.cloud import storage
import traceback
import shutil

# Initialize tracing
from ..common.tracing import get_tracer

# Global variables to hold initialized clients
storage_client = None
cache_bucket = None
tracer = None
GCS_WORKER_CACHE_BUCKET = None


def init_merger():
    """Initialize global clients and configuration for the merger."""
    global storage_client, cache_bucket, tracer, GCS_WORKER_CACHE_BUCKET

    if storage_client is not None:
        return

    # Set up tracing
    tracer = get_tracer(__name__)

    # Initialized at cold start
    GCS_WORKER_CACHE_BUCKET = os.environ["GCS_WORKER_CACHE_BUCKET"]

    storage_client = storage.Client()
    cache_bucket = storage_client.bucket(GCS_WORKER_CACHE_BUCKET)


def fetch_and_merge_pdfs(output_path):
    """
    Fetch all song sheet PDFs from GCS cache bucket and merge them into a single PDF.

    Args:
        output_path: Path where the merged PDF should be saved.

    Returns:
        str: Path to the merged PDF file (same as output_path)
    """
    with tracer.start_as_current_span("fetch_and_merge_pdfs") as main_span:
        # Create temporary directory for downloads
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Downloading PDFs to temporary directory: {temp_dir}")
            main_span.set_attribute("temp_dir", temp_dir)

            # Fetch all blobs with song-sheets prefix
            with tracer.start_as_current_span("list_blobs") as list_span:
                prefix = "song-sheets/"
                blobs = list(cache_bucket.list_blobs(prefix=prefix))
                pdf_blobs = [blob for blob in blobs if blob.name.endswith(".pdf")]

                list_span.set_attribute("total_blobs", len(blobs))
                list_span.set_attribute("pdf_blobs", len(pdf_blobs))
                main_span.set_attribute("pdf_count", len(pdf_blobs))

            if not pdf_blobs:
                print("No PDF files found in the cache bucket")
                return None

            downloaded_files = []
            file_metadata = []

            # Download each PDF file and collect metadata
            with tracer.start_as_current_span("download_files") as downloads_span:
                for blob in pdf_blobs:
                    # Replace path separators with underscores for local filename
                    filename = blob.name.replace("/", "_")
                    local_path = os.path.join(temp_dir, filename)

                    print(f"Downloading {blob.name} to {filename}")
                    with tracer.start_as_current_span("download_file") as download_span:
                        download_span.set_attribute("blob_name", blob.name)
                        download_span.set_attribute("local_path", local_path)
                        blob.download_to_filename(local_path)
                        print(f"Downloading {blob.name} to {filename}")

                    downloaded_files.append(local_path)

                    # Extract metadata for TOC
                    blob_metadata = blob.metadata or {}
                    song_name = blob_metadata.get("gdrive-file-name", "Unknown Song")
                    file_metadata.append(
                        {"path": local_path, "name": song_name, "blob_name": blob.name}
                    )

                downloads_span.set_attribute("downloaded_count", len(downloaded_files))

            # Sort files and metadata for consistent ordering
            file_metadata.sort(key=lambda x: x["name"])

            # Merge PDFs
            with tracer.start_as_current_span("merge_pdfs") as merge_span:
                print(f"Merging {len(file_metadata)} PDF files...")
                merger = PyPDF2.PdfMerger()
                toc_entries = []
                current_page = 0

                for file_info in file_metadata:
                    print(f"Adding {file_info['name']} to merger")

                    # Count pages in this PDF to track TOC positions
                    with open(file_info["path"], "rb") as pdf_file:
                        pdf_reader = PyPDF2.PdfReader(pdf_file)
                        page_count = len(pdf_reader.pages)

                    # Add to TOC (page numbers are 1-based for user display)
                    toc_entries.append([1, file_info["name"], current_page + 1])
                    current_page += page_count

                    merger.append(file_info["path"])

                # Write combined PDF to temporary file
                temp_merged_path = os.path.join(temp_dir, "merged.pdf")
                merger.write(temp_merged_path)
                merger.close()

                merge_span.set_attribute("temp_merged_path", temp_merged_path)
                merge_span.set_attribute("merged_files", len(file_metadata))
                merge_span.set_attribute("toc_entries", len(toc_entries))

                print(f"Successfully created merged PDF: {temp_merged_path}")

                # Add table of contents using PyMuPDF
                with tracer.start_as_current_span("add_toc") as toc_span:
                    print("Adding table of contents to merged PDF...")

                    # Open the merged PDF with PyMuPDF
                    doc = fitz.open(temp_merged_path)

                    # Set the table of contents
                    doc.set_toc(toc_entries)

                    # Save to a new temporary file with TOC
                    temp_with_toc_path = os.path.join(temp_dir, "with_toc.pdf")
                    doc.save(temp_with_toc_path)
                    doc.close()

                    toc_span.set_attribute("toc_entries_added", len(toc_entries))
                    toc_span.set_attribute("temp_with_toc_path", temp_with_toc_path)
                    print(f"Added {len(toc_entries)} entries to table of contents")

                # Upload merged PDF back to GCS cache
                with tracer.start_as_current_span("upload_to_cache") as upload_span:
                    cache_blob = cache_bucket.blob("merged-pdf/latest.pdf")
                    print("Uploading merged PDF to cache at: merged-pdf/latest.pdf")
                    cache_blob.upload_from_filename(
                        temp_with_toc_path, content_type="application/pdf"
                    )
                    upload_span.set_attribute(
                        "cache_blob_name", "merged-pdf/latest.pdf"
                    )

                # Copy the file with TOC to the final output location
                print(f"Copying merged PDF with TOC to: {output_path}")
                shutil.copy2(temp_with_toc_path, output_path)
                merge_span.set_attribute("final_output_path", output_path)

                return output_path


def merger_main(request):
    """HTTP Cloud Function for merging PDFs from GCS cache."""
    init_merger()
    with tracer.start_as_current_span("merger_main") as main_span:
        try:
            print("Starting PDF merge operation")

            # Create a temporary file for the merged PDF
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_output_path = temp_file.name

            try:
                # Fetch and merge PDFs
                with tracer.start_as_current_span("merge_operation") as merge_span:
                    result_path = fetch_and_merge_pdfs(temp_output_path)

                    if not result_path:
                        main_span.set_attribute("status", "no_files")
                        return {"error": "No PDF files found to merge"}, 404

                    merge_span.set_attribute("merged_pdf_path", result_path)

                # Read the merged PDF data
                with tracer.start_as_current_span("return_pdf") as return_span:
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
