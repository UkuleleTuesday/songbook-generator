import os
import tempfile
import PyPDF2
import functions_framework
from google.cloud import storage
import traceback

# Initialize tracing
from common.tracing import setup_tracing, get_tracer

# Initialized at cold start
GCS_WORKER_CACHE_BUCKET = os.environ["GCS_WORKER_CACHE_BUCKET"]

# Set up tracing
setup_tracing("songbook-generator-merger")

storage_client = storage.Client()
cache_bucket = storage_client.bucket(GCS_WORKER_CACHE_BUCKET)

# Initialize tracer
tracer = get_tracer(__name__)


def fetch_and_merge_pdfs():
    """
    Fetch all song sheet PDFs from GCS cache bucket and merge them into a single PDF.

    Returns:
        str: Path to the merged PDF file
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

            # Download each PDF file
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

                downloads_span.set_attribute("downloaded_count", len(downloaded_files))

            # Sort files for consistent ordering
            downloaded_files.sort()

            # Merge PDFs
            with tracer.start_as_current_span("merge_pdfs") as merge_span:
                print(f"Merging {len(downloaded_files)} PDF files...")
                merger = PyPDF2.PdfMerger()

                for file_path in downloaded_files:
                    print(f"Adding {os.path.basename(file_path)} to merger")
                    merger.append(file_path)

                # Write combined PDF to temporary file
                output_path = os.path.join(temp_dir, "combined.pdf")
                merger.write(output_path)
                merger.close()

                merge_span.set_attribute("output_path", output_path)
                merge_span.set_attribute("merged_files", len(downloaded_files))

                print(f"Successfully created combined PDF: {output_path}")
                return output_path


@functions_framework.http
def main(request):
    """HTTP Cloud Function for merging PDFs from GCS cache."""
    with tracer.start_as_current_span("merger_main") as main_span:
        try:
            print("Starting PDF merge operation")

            # Fetch and merge PDFs
            with tracer.start_as_current_span("merge_operation") as merge_span:
                merged_pdf_path = fetch_and_merge_pdfs()

                if not merged_pdf_path:
                    main_span.set_attribute("status", "no_files")
                    return {"error": "No PDF files found to merge"}, 404

                merge_span.set_attribute("merged_pdf_path", merged_pdf_path)

            # Read the merged PDF and return it
            with tracer.start_as_current_span("return_pdf") as return_span:
                with open(merged_pdf_path, "rb") as pdf_file:
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

        except Exception as e:
            main_span.set_attribute("error", str(e))
            main_span.set_attribute("status", "failed")

            print(f"Merge operation failed: {str(e)}")
            print("Error details:")
            print(traceback.format_exc())

            return {"error": f"Internal error during PDF merge: {str(e)}"}, 500


def cli_main():
    """CLI interface for merging PDFs from GCS cache."""
    import argparse

    parser = argparse.ArgumentParser(description="Merge PDFs from GCS cache bucket")
    parser.add_argument(
        "--output",
        "-o",
        default="merged-songbook.pdf",
        help="Output file path for merged PDF (default: merged-songbook.pdf)",
    )

    args = parser.parse_args()

    try:
        print("Starting PDF merge operation (CLI mode)")

        merged_pdf_path = fetch_and_merge_pdfs()

        if not merged_pdf_path:
            print("Error: No PDF files found to merge")
            return 1

        # Copy the merged PDF to the specified output location
        import shutil

        shutil.copy2(merged_pdf_path, args.output)

        print(f"Successfully created merged PDF: {args.output}")
        return 0

    except Exception as e:
        print(f"Merge operation failed: {str(e)}")
        print("Error details:")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(cli_main())
