#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pyyaml>=6.0.2",
#   "google-cloud-storage>=2.16",
# ]
# ///
"""Restore edition latest.json pointers to earlier published artifacts.

Usage:
    restore-publish-pointers.py <bucket> [spec-file]

Reads the restore spec (default: .github/restore-pointers.yml) and, for each
entry, rewrites <edition>/latest.json to point at the named PDF and its
sibling .manifest.json, with generated_at taken from that manifest and
visibility/pinned re-read from the edition config (defaults public/unpinned
when no config exists). Both artifacts must already exist in the bucket —
this script never uploads a book, only moves the pointer.
"""

import json
import sys
from pathlib import Path

import yaml
from google.cloud import storage

CACHE_CONTROL = "public, max-age=60"


def read_publish_vars(edition: str) -> tuple[str, bool]:
    edition_yaml = Path(f"generator/config/songbooks/{edition}.yaml")
    try:
        with open(edition_yaml) as f:
            cfg = yaml.safe_load(f)
        pub = cfg.get("publish", {}) if isinstance(cfg, dict) else {}
        return pub.get("visibility", "public"), bool(pub.get("pinned", False))
    except OSError:
        return "public", False


def restore_edition(bucket, edition: str, pdf_filename: str) -> str:
    if not pdf_filename.endswith(".pdf"):
        raise ValueError(f"not a pdf filename: {pdf_filename}")
    manifest_filename = pdf_filename[: -len(".pdf")] + ".manifest.json"

    pdf_blob = bucket.blob(f"{edition}/{pdf_filename}")
    if not pdf_blob.exists():
        raise FileNotFoundError(f"{edition}/{pdf_filename} not in bucket")
    manifest_blob = bucket.blob(f"{edition}/{manifest_filename}")
    manifest = json.loads(manifest_blob.download_as_text())

    visibility, pinned = read_publish_vars(edition)
    latest = {
        "pdf_filename": pdf_filename,
        "manifest_filename": manifest_filename,
        "generated_at": manifest["generated_at"],
        "visibility": visibility,
        "pinned": pinned,
    }

    latest_blob = bucket.blob(f"{edition}/latest.json")
    if json.loads(latest_blob.download_as_text()) == latest:
        return "already restored"
    latest_blob.cache_control = CACHE_CONTROL
    latest_blob.upload_from_string(json.dumps(latest), content_type="application/json")
    return f"restored to {pdf_filename} (generated_at={manifest['generated_at']})"


def main() -> None:
    if len(sys.argv) < 2:
        print(
            f"Usage: {Path(sys.argv[0]).name} <bucket> [spec-file]",
            file=sys.stderr,
        )
        sys.exit(1)

    bucket_name = sys.argv[1]
    spec_file = (
        Path(sys.argv[2])
        if len(sys.argv) >= 3
        else Path(".github/restore-pointers.yml")
    )

    with open(spec_file) as f:
        spec = yaml.safe_load(f) or {}
    restores = spec.get("restores") or []
    if not restores:
        print("No restores listed; nothing to do.")
        return

    bucket = storage.Client().bucket(bucket_name)
    failures = 0
    for entry in restores:
        edition = entry["edition"]
        try:
            outcome = restore_edition(bucket, edition, entry["pdf_filename"])
        except Exception as e:  # noqa: BLE001 - report and keep restoring the rest
            outcome = f"FAILED: {e}"
            failures += 1
        print(f"{edition}: {outcome}")

    if failures:
        sys.exit(1)
    print("✅ Pointers restored")


if __name__ == "__main__":
    main()
