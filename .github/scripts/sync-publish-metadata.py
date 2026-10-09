#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pyyaml>=6.0.2",
#   "google-cloud-storage>=2.16",
# ]
# ///
"""Sync publish metadata (visibility/pinned/featured_until) from edition
configs to GCS.

Usage:
    sync-publish-metadata.py <bucket> [configs-dir]

For each edition YAML in <configs-dir> (default: generator/config/songbooks),
reads the edition's existing latest.json in <bucket> and, when its publish
fields differ from the config's publish block, patches those keys and
re-uploads the file. Editions with no latest.json (never
published) are skipped — this script never creates one.

This lets a publish metadata change in an edition config reach the bucket
without regenerating the songbook, which matters for retired editions that
will never be re-published.
"""

import json
import sys
from pathlib import Path

import yaml
from google.api_core.exceptions import NotFound
from google.cloud import storage

CACHE_CONTROL = "public, max-age=60"


def publish_vars(pub: dict) -> dict:
    featured_until = pub.get("featured_until")
    return {
        "visibility": pub.get("visibility", "public"),
        "pinned": bool(pub.get("pinned", False)),
        # YAML loads an unquoted date as datetime.date; str() gives YYYY-MM-DD.
        "featured_until": str(featured_until) if featured_until else None,
    }


def read_publish_vars(edition_yaml: Path) -> dict:
    with open(edition_yaml) as f:
        cfg = yaml.safe_load(f)
    pub = cfg.get("publish", {}) if isinstance(cfg, dict) else {}
    return publish_vars(pub)


def sync_edition(bucket, edition: str, publish: dict) -> str:
    blob = bucket.blob(f"{edition}/latest.json")
    try:
        latest = json.loads(blob.download_as_text())
    except NotFound:
        return "not published, skipped"

    # A latest.json written before a field existed reads as None, so editions
    # that don't set it aren't rewritten just to add the key.
    if all(latest.get(key) == value for key, value in publish.items()):
        return "unchanged"

    latest.update(publish)
    blob.cache_control = CACHE_CONTROL
    blob.upload_from_string(json.dumps(latest), content_type="application/json")
    fields = ", ".join(f"{key}={value}" for key, value in publish.items())
    return f"updated ({fields})"


def main() -> None:
    if len(sys.argv) < 2:
        print(
            f"Usage: {Path(sys.argv[0]).name} <bucket> [configs-dir]",
            file=sys.stderr,
        )
        sys.exit(1)

    bucket_name = sys.argv[1]
    configs_dir = (
        Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("generator/config/songbooks")
    )

    bucket = storage.Client().bucket(bucket_name)
    failures = 0
    for edition_yaml in sorted(configs_dir.glob("*.yaml")):
        edition = edition_yaml.stem
        try:
            outcome = sync_edition(bucket, edition, read_publish_vars(edition_yaml))
        except Exception as e:  # noqa: BLE001 - report and keep syncing the rest
            outcome = f"FAILED: {e}"
            failures += 1
        print(f"{edition}: {outcome}")

    if failures:
        sys.exit(1)
    print("✅ Publish metadata in sync")


if __name__ == "__main__":
    main()
