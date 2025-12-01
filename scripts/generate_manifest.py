#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "click",
#   "packaging",
#   "google-cloud-storage",
# ]
# ///

import json
import os
import re
from datetime import datetime, timezone

import click
from google.cloud import exceptions, storage


@click.command()
@click.option(
    "--bucket-name",
    required=True,
    help="GCS bucket name where songbooks and manifest are stored.",
)
@click.option(
    "--new-file-paths",
    required=True,
    help="Space-separated string of newly generated GCS file paths.",
)
@click.option(
    "--editions-order",
    envvar="SONGBOOK_EDITIONS",
    help="Space-separated string of editions in the desired order.",
    default="",
)
def generate_manifest(bucket_name: str, new_file_paths: str, editions_order: str):
    """
    Updates or creates a manifest.json file in a GCS bucket.

    Reads the existing manifest, updates it with new songbook files,
    and prints the new manifest to stdout.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    manifest_blob = bucket.blob("manifest.json")

    # Load existing manifest or create a new one
    try:
        manifest_data = json.loads(manifest_blob.download_as_string())
        editions = manifest_data.get("editions", {})
    except (exceptions.NotFound, json.JSONDecodeError):
        editions = {}

    # Filename pattern: ukulele-tuesday-songbook-<edition>-<YYYY-MM-DD>.pdf
    filename_re = re.compile(
        r"ukulele-tuesday-songbook-(?P<edition>.*)-(?P<date>\d{4}-\d{2}-\d{2})\.pdf$"
    )

    # Process only the newly generated files
    for path in new_file_paths.strip().split():
        if not path.startswith("gs://") or not path.endswith(".pdf"):
            continue

        blob_name = os.path.basename(path)
        match = filename_re.match(blob_name)
        if match:
            edition_name = match.group("edition")
            blob = bucket.blob(blob_name)
            blob.reload()  # Reload to get metadata

            editions[edition_name] = {
                "url": f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                "updated_utc": blob.updated.isoformat(),
            }

    # Order editions based on the provided order
    ordered_editions = {}
    ordered_edition_keys = editions_order.split()

    for key in ordered_edition_keys:
        if key in editions:
            ordered_editions[key] = editions[key]

    manifest = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "editions": ordered_editions,
    }

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    generate_manifest()
