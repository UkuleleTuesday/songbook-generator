import os
import tempfile
import PyPDF2
from google.cloud import storage


def fetch_and_merge_pdfs():
    """
    Fetch all song sheet PDFs from GCS cache bucket and merge them into a single PDF.
    """
    # Get environment variables
    bucket_name = os.getenv("GCS_WORKER_CACHE_BUCKET")
    if not bucket_name:
        raise ValueError("GCS_WORKER_CACHE_BUCKET environment variable not set")

    # Set up GCS client
    storage_client = storage.Client()
    bucket = storage_client.get_bucket(bucket_name)

    # Create temporary directory for downloads
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Downloading PDFs to temporary directory: {temp_dir}")

        # Fetch all blobs with song-sheets prefix
        prefix = "song-sheets/"
        blobs = bucket.list_blobs(prefix=prefix)

        downloaded_files = []

        # Download each PDF file
        for blob in blobs:
            if blob.name.endswith(".pdf"):
                # Replace path separators with underscores for local filename
                filename = blob.name.replace("/", "_")
                local_path = os.path.join(temp_dir, filename)

                print(f"Downloading {blob.name} to {filename}")
                blob.download_to_filename(local_path)
                downloaded_files.append(local_path)

        if not downloaded_files:
            print("No PDF files found in the cache bucket")
            return

        # Sort files for consistent ordering
        downloaded_files.sort()

        # Merge PDFs
        print(f"Merging {len(downloaded_files)} PDF files...")
        merger = PyPDF2.PdfMerger()

        for file_path in downloaded_files:
            print(f"Adding {os.path.basename(file_path)} to merger")
            merger.append(file_path)

        # Write combined PDF
        output_path = "combined.pdf"
        merger.write(output_path)
        merger.close()

        print(f"Successfully created combined PDF: {output_path}")


if __name__ == "__main__":
    fetch_and_merge_pdfs()
