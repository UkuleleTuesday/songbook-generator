#!/usr/bin/env python

import json
import os
import re
import sys
from datetime import datetime, timezone

import click
from google.cloud import storage


@click.command()
@click.option(
    "--bucket-name",
    envvar="GCS_SONGBOOKS_BUCKET",
    required=True,
    help="GCS bucket name for songbooks.",
)
def generate_manifest(bucket_name: str):
    """
    Generates a manifest.json file for songbook editions in a GCS bucket.

    Lists all PDF files, extracts edition metadata from filenames that match
    the expected pattern, and outputs a JSON manifest to stdout.
    """
    try:
        storage_client = storage.Client()
        blobs = storage_client.list_blobs(bucket_name, prefix="ukulele-tuesday-songbook-")
    except Exception as e:
        print(f"Error: Failed to connect to GCS bucket '{bucket_name}'. {e}", file=sys.stderr)
        sys.exit(1)

    editions = {}
    # Filename pattern: ukulele-tuesday-songbook-<edition>-<YYYY-MM-DD>.pdf
    filename_re = re.compile(r"ukulele-tuesday-songbook-(?P<edition>.*)-(?P<date>\d{4}-\d{2}-\d{2})\.pdf$")

    for blob in blobs:
        if not blob.name.endswith(".pdf"):
            continue

        match = filename_re.match(os.path.basename(blob.name))
        if match:
            edition_name = match.group("edition")
            editions[edition_name] = {
                "url": f"https://storage.googleapis.com/{bucket_name}/{blob.name}",
                "updated_utc": blob.updated.isoformat(),
            }

    manifest = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "editions": editions,
    }

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    generate_manifest()
