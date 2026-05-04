#!/usr/bin/env python3
"""Verify which songs in an edition config are found/missing in Drive."""

import sys
import subprocess
import yaml
from pathlib import Path


def get_edition_song_names(edition_id: str) -> list[str]:
    config_path = (
        Path(__file__).parent.parent / "generator" / "config" / "songbooks" / f"{edition_id}.yaml"
    )
    with open(config_path) as f:
        config = yaml.safe_load(f)

    for flt in config.get("filters", []):
        if flt.get("key") == "name" and flt.get("operator") == "in":
            return flt["value"]

    print(f"No 'name: in' filter found in {edition_id}.yaml")
    sys.exit(1)


def get_matched_names(edition_id: str) -> set[str]:
    result = subprocess.run(
        ["uv", "run", "songbook-tools", "--log-level", "error", "songs", "list", "--edition", edition_id],
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main():
    edition_id = sys.argv[1] if len(sys.argv) > 1 else "monopolele-2026"
    print(f"Verifying edition: {edition_id}\n")

    expected = get_edition_song_names(edition_id)
    matched = get_matched_names(edition_id)

    found = [s for s in expected if s in matched]
    missing = [s for s in expected if s not in matched]

    print(f"Found ({len(found)}/{len(expected)}):")
    for s in found:
        print(f"  ✓ {s}")

    if missing:
        print(f"\nMissing ({len(missing)}):")
        for s in missing:
            print(f"  ✗ {s}")
    else:
        print("\nAll songs matched!")


if __name__ == "__main__":
    main()
