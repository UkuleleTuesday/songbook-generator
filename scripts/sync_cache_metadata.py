#!/usr/bin/env python3
"""
Sync GCS cache metadata with Google Drive file information.

This script takes a Google Drive folder ID as input, fetches all files from that folder,
and updates the metadata of corresponding cached files in GCS with their Drive file ID
and name.
"""

import argparse
import sys
from google.cloud import storage
from generator.gdrive import authenticate_drive, query_drive_files


def get_cached_files(storage_client, bucket_name, prefix="song-sheets/"):
    """
    Get all cached files from GCS under the specified prefix.

    Args:
        storage_client: GCS client
        bucket_name: Name of the GCS bucket
        prefix: Prefix to filter files (default: "song-sheets/")

    Returns:
        List of blob objects
    """
    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix))
    return blobs


def extract_drive_file_id_from_blob_name(blob_name, prefix="song-sheets/"):
    """
    Extract the Drive file ID from the blob name.

    Args:
        blob_name: Name of the blob (e.g., "song-sheets/1234567890.pdf")
        prefix: Prefix to remove

    Returns:
        Drive file ID or None if not extractable
    """
    if not blob_name.startswith(prefix):
        return None

    filename = blob_name[len(prefix) :]
    if filename.endswith(".pdf"):
        return filename[:-4]  # Remove .pdf extension

    return None


def sync_cache_metadata(folder_id, bucket_name, dry_run=False):
    """
    Sync cache metadata with Google Drive file information.

    Args:
        folder_id: Google Drive folder ID to sync from
        bucket_name: GCS bucket name containing cached files
        dry_run: If True, only print what would be done without making changes
    """
    print(f"Syncing cache metadata for folder {folder_id}")
    print(f"Target bucket: {bucket_name}")

    # Initialize clients
    print("Authenticating with Google Drive...")
    drive = authenticate_drive()

    print("Initializing GCS client...")
    storage_client = storage.Client()

    # Get Drive files
    print(f"Fetching files from Google Drive folder {folder_id}...")
    drive_files = query_drive_files(drive, folder_id)
    print(f"Found {len(drive_files)} files in Drive folder")

    # Create a mapping of file ID to file info
    drive_file_map = {file["id"]: file for file in drive_files}

    # Get cached files
    print("Fetching cached files from GCS...")
    cached_blobs = get_cached_files(storage_client, bucket_name)
    print(f"Found {len(cached_blobs)} cached files")

    # Process each cached file
    updated_count = 0
    skipped_count = 0
    error_count = 0

    for blob in cached_blobs:
        drive_file_id = extract_drive_file_id_from_blob_name(blob.name)

        if not drive_file_id:
            print(f"  SKIP: Cannot extract Drive file ID from {blob.name}")
            skipped_count += 1
            continue

        if drive_file_id not in drive_file_map:
            print(f"  SKIP: Drive file {drive_file_id} not found in folder {folder_id}")
            skipped_count += 1
            continue

        drive_file = drive_file_map[drive_file_id]

        # Check if metadata already exists and is correct
        current_metadata = blob.metadata or {}
        expected_file_id = drive_file["id"]
        expected_file_name = drive_file["name"]

        if (
            current_metadata.get("gdrive_file_id") == expected_file_id
            and current_metadata.get("gdrive_file_name") == expected_file_name
        ):
            print(f"  OK: {blob.name} metadata already up to date")
            continue

        # Update metadata
        new_metadata = dict(current_metadata)
        new_metadata["gdrive_file_id"] = expected_file_id
        new_metadata["gdrive_file_name"] = expected_file_name

        if dry_run:
            print(f"  DRY-RUN: Would update {blob.name}")
            print(f"    gdrive_file_id: {expected_file_id}")
            print(f"    gdrive_file_name: {expected_file_name}")
        else:
            try:
                blob.metadata = new_metadata
                blob.patch()
                print(f"  UPDATE: {blob.name}")
                print(f"    gdrive_file_id: {expected_file_id}")
                print(f"    gdrive_file_name: {expected_file_name}")
                updated_count += 1
            except Exception as e:
                print(f"  ERROR: Failed to update {blob.name}: {e}")
                error_count += 1

    # Print summary
    print("\nSummary:")
    print(f"  Updated: {updated_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total processed: {len(cached_blobs)}")


def main():
    parser = argparse.ArgumentParser(
        description="Sync GCS cache metadata with Google Drive file information"
    )
    parser.add_argument("folder_id", help="Google Drive folder ID to sync from")
    parser.add_argument(
        "--bucket",
        default="songbook-generator-worker-cache",
        help="GCS bucket name (default: songbook-generator-worker-cache)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be done without making changes",
    )

    args = parser.parse_args()

    try:
        sync_cache_metadata(args.folder_id, args.bucket, args.dry_run)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
