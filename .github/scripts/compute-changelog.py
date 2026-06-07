#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Enrich a songbook manifest with an added/removed-songs changelog.

Usage:
    compute-changelog.py <new-manifest> <previous-manifest|"none"> [previous-manifest-filename]

Diffs the new manifest's ``content_info.file_names`` against the previously
published manifest and writes a top-level ``changelog`` object into the new
manifest in place. If the previous manifest is missing, the literal string
``none``, or unparseable, an empty changelog is written (first-run behaviour).
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional


def load_file_names(manifest: dict[str, Any]) -> list[str]:
    """Safely read the list of song file names from a manifest dict."""
    return manifest.get("content_info", {}).get("file_names", []) or []


def compute_changelog(
    new_names: list[str],
    old_names: Optional[list[str]],
    previous_manifest: Optional[str],
    previous_generated_at: Optional[str],
) -> dict[str, Any]:
    """Compute the changelog object diffing new vs. previous song lists.

    Pure function (no I/O). ``old_names`` of ``None`` means there is no
    previous published manifest (first run), which yields empty added/removed
    lists so a brand-new edition does not report every song as "added".
    """
    if old_names is None:
        added: list[str] = []
        removed: list[str] = []
    else:
        old_set = set(old_names)
        new_set = set(new_names)
        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
    return {
        "previous_manifest": previous_manifest,
        "previous_generated_at": previous_generated_at,
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    if len(sys.argv) < 3:
        print(
            f"Usage: {Path(sys.argv[0]).name} "
            '<new-manifest> <previous-manifest|"none"> [previous-manifest-filename]',
            file=sys.stderr,
        )
        sys.exit(1)

    new_manifest_path = Path(sys.argv[1])
    previous_arg = sys.argv[2]
    previous_name = sys.argv[3] if len(sys.argv) >= 4 and sys.argv[3] else None

    # The new manifest must exist and be readable; anything else is a real error.
    try:
        new_manifest = _load_manifest(new_manifest_path)
    except (OSError, ValueError) as e:
        print(
            f"Error: could not read new manifest {new_manifest_path}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    old_names: Optional[list[str]] = None
    previous_generated_at: Optional[str] = None
    previous_manifest_ref: Optional[str] = None

    if previous_arg != "none":
        previous_path = Path(previous_arg)
        try:
            previous_manifest = _load_manifest(previous_path)
            old_names = load_file_names(previous_manifest)
            previous_generated_at = previous_manifest.get("generated_at")
            previous_manifest_ref = previous_name or previous_path.name
        except (OSError, ValueError) as e:
            # First-run / corrupt previous: degrade to an empty changelog.
            print(
                f"Warning: could not read previous manifest {previous_path}: {e}; "
                "writing empty changelog.",
                file=sys.stderr,
            )

    changelog = compute_changelog(
        new_names=load_file_names(new_manifest),
        old_names=old_names,
        previous_manifest=previous_manifest_ref,
        previous_generated_at=previous_generated_at,
    )
    new_manifest["changelog"] = changelog

    with open(new_manifest_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, indent=2)

    print(
        f"✅ Wrote changelog to {new_manifest_path}: "
        f"{changelog['added_count']} added, {changelog['removed_count']} removed "
        f"(previous: {previous_manifest_ref or '<none>'})"
    )


if __name__ == "__main__":
    main()
