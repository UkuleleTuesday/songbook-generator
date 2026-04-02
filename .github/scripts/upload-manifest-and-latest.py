#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pyyaml>=6.0.2",
# ]
# ///
"""Upload a songbook manifest and generate/upload latest.json to GCS.

Usage:
    upload-manifest-and-latest.py <edition> <songbooks-dir>

Environment:
    GCS_SONGBOOKS_BUCKET  Target GCS bucket name (required)

Finds the .pdf and .manifest.json files in <songbooks-dir>, uploads the
manifest, then creates and uploads a latest.json that includes publish
metadata read from the edition YAML config.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def gcs_upload(src: Path, dest: str, cache_control: str) -> None:
    subprocess.run(
        [
            "gcloud",
            "storage",
            "cp",
            str(src),
            dest,
            f"--cache-control={cache_control}",
        ],
        check=True,
    )


def read_publish_vars(edition_yaml: Path) -> tuple[str, bool]:
    try:
        with open(edition_yaml) as f:
            cfg = yaml.safe_load(f)
        pub = cfg.get("publish", {}) if isinstance(cfg, dict) else {}
        return pub.get("visibility", "public"), bool(pub.get("pinned", False))
    except (OSError, yaml.YAMLError):
        return "public", False


def main() -> None:
    if len(sys.argv) < 3:
        print(
            f"Usage: {Path(sys.argv[0]).name} <edition> <songbooks-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    edition = sys.argv[1]
    songbooks_dir = Path(sys.argv[2])
    gcs_bucket = os.environ["GCS_SONGBOOKS_BUCKET"]

    pdf_file = next(songbooks_dir.glob("*.pdf"), None)
    manifest_file = next(songbooks_dir.glob("*.manifest.json"), None)

    if manifest_file is None:
        print("Manifest file not found, skipping upload.", file=sys.stderr)
        sys.exit(1)

    pdf_filename = pdf_file.name if pdf_file else ""
    manifest_filename = manifest_file.name

    # Upload manifest
    dest_manifest = f"gs://{gcs_bucket}/{edition}/{manifest_filename}"
    print(f"Uploading '{manifest_filename}' to '{dest_manifest}'")
    gcs_upload(manifest_file, dest_manifest, "public, max-age=600")
    print("✅ Successfully uploaded manifest")

    # Read edition publish config
    edition_yaml = Path(f"generator/config/songbooks/{edition}.yaml")
    visibility, pinned = read_publish_vars(edition_yaml)

    # Build and write latest.json
    latest = {
        "pdf_filename": pdf_filename,
        "manifest_filename": manifest_filename,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "visibility": visibility,
        "pinned": pinned,
    }
    latest_json = Path("latest.json")
    latest_json.write_text(json.dumps(latest))
    print(latest_json.read_text())

    # Upload latest.json
    dest_latest = f"gs://{gcs_bucket}/{edition}/latest.json"
    print(f"Uploading latest.json to {dest_latest}")
    gcs_upload(latest_json, dest_latest, "public, max-age=60")
    print("✅ Successfully uploaded latest.json")


if __name__ == "__main__":
    main()
