#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "click",
#   "google-cloud-storage",
# ]
# ///

import json
import os
import re
from datetime import datetime, timezone

import click
from google.cloud import storage


@click.command()
@click.option(
    "--file-paths",
    required=True,
    help="Space-separated string of GCS file paths.",
)
@click.option(
    "--editions-order",
    envvar="SONGBOOK_EDITIONS",
    help="Space-separated string of editions in the desired order.",
    default="",
)
def generate_manifest(file_paths: str, editions_order: str):
    """
    Generates a manifest.json file from a list of GCS file paths.

    Extracts edition metadata from filenames that match the expected
    pattern and outputs a JSON manifest to stdout.
    """
    storage_client = storage.Client()
    paths = file_paths.strip().split()

    found_editions = {}
    # Filename pattern: ukulele-tuesday-songbook-<edition>-<YYYY-MM-DD>.pdf
    filename_re = re.compile(
        r"ukulele-tuesday-songbook-(?P<edition>.*)-(?P<date>\d{4}-\d{2}-\d{2})\.pdf$"
    )

    for path in paths:
        if not path.startswith("gs://") or not path.endswith(".pdf"):
            continue

        parts = path.replace("gs://", "").split("/", 1)
        if len(parts) != 2:
            continue
        bucket_name, blob_name = parts

        match = filename_re.match(os.path.basename(blob_name))
        if match:
            blob = storage.Blob(
                name=blob_name, bucket=storage_client.bucket(bucket_name)
            )
            # The blob needs to be reloaded to get all the metadata
            blob.reload()

            edition_name = match.group("edition")
            found_editions[edition_name] = {
                "url": f"https://storage.googleapis.com/{bucket_name}/{blob_name}",
                "updated_utc": blob.updated.isoformat(),
            }

    # Order editions based on the provided order, appending any found but not specified editions at the end.
    ordered_editions = {}
    ordered_edition_keys = editions_order.split()
    found_keys = set(found_editions.keys())

    # Add editions in the specified order
    for key in ordered_edition_keys:
        if key in found_editions:
            ordered_editions[key] = found_editions[key]

    # Add any remaining found editions that were not in the order list
    for key in sorted(list(found_keys - set(ordered_edition_keys))):
        ordered_editions[key] = found_editions[key]

    manifest = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "editions": ordered_editions,
    }

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    generate_manifest()
