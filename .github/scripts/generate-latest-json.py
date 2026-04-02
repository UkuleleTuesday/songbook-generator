#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pyyaml>=6.0.2",
# ]
# ///
"""Generate a latest.json file for a songbook edition.

Usage:
    generate-latest-json.py <edition> <songbooks-dir> [output-file]

Finds the .pdf and .manifest.json files in <songbooks-dir>, reads publish
metadata from the edition YAML config, then writes latest.json to
<output-file> (defaults to latest.json in the current directory).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


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
            f"Usage: {Path(sys.argv[0]).name} <edition> <songbooks-dir> [output-file]",
            file=sys.stderr,
        )
        sys.exit(1)

    edition = sys.argv[1]
    songbooks_dir = Path(sys.argv[2])
    output_file = Path(sys.argv[3]) if len(sys.argv) >= 4 else Path("latest.json")

    pdf_file = next(songbooks_dir.glob("*.pdf"), None)
    manifest_file = next(songbooks_dir.glob("*.manifest.json"), None)

    if manifest_file is None:
        print("Manifest file not found, skipping.", file=sys.stderr)
        sys.exit(1)

    pdf_filename = pdf_file.name if pdf_file else ""
    manifest_filename = manifest_file.name

    edition_yaml = Path(f"generator/config/songbooks/{edition}.yaml")
    visibility, pinned = read_publish_vars(edition_yaml)

    latest = {
        "pdf_filename": pdf_filename,
        "manifest_filename": manifest_filename,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "visibility": visibility,
        "pinned": pinned,
    }
    latest_json = json.dumps(latest)
    output_file.write_text(latest_json)
    print(latest_json)
    print(f"✅ Written latest.json to {output_file}")


if __name__ == "__main__":
    main()
