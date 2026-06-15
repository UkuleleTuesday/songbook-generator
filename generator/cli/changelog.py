import json
import sys
from pathlib import Path
from typing import Any, Optional

import click

from ..changelog import (
    DEFAULT_MAX_ENTRIES,
    backfill_history,
    build_entry,
    empty_history,
    update_history,
)
from .utils import global_options


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _is_missing(value: Optional[str]) -> bool:
    """True for the workflow's 'no previous' sentinels (empty or literal 'none')."""
    return not value or value == "none"


@click.command(name="update-changelog")
@global_options
@click.option(
    "--new-manifest",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the newly generated manifest.json.",
)
@click.option(
    "--previous-manifest",
    default=None,
    help="Path to the previously published manifest (or 'none' for first publish).",
)
@click.option(
    "--previous-manifest-filename",
    default=None,
    help="Published filename of the previous manifest (for the entry's reference).",
)
@click.option(
    "--changes",
    "changes_path",
    default=None,
    help="Path to the existing changes.json to update (optional).",
)
@click.option("--edition", required=True, help="Edition id, e.g. 'current'.")
@click.option(
    "--manifest-filename",
    default=None,
    help="Published filename for the new manifest (defaults to its basename).",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("changes.json"),
    help="Where to write the updated changes.json.",
)
@click.option(
    "--max-entries",
    type=int,
    default=DEFAULT_MAX_ENTRIES,
    help="Maximum number of history entries to keep.",
)
def update_changelog(
    new_manifest: Path,
    previous_manifest: Optional[str],
    previous_manifest_filename: Optional[str],
    changes_path: Optional[str],
    edition: str,
    manifest_filename: Optional[str],
    output: Path,
    max_entries: int,
    **kwargs,
):
    """Append a changelog entry to an edition's changes.json history.

    Diffs the new manifest's songs against the previously published manifest and
    prepends an entry when the song list changed. No-op re-publishes leave the
    history untouched (the diff is empty, so nothing is appended).
    """
    new = _load_json(new_manifest)
    manifest_filename = manifest_filename or new_manifest.name

    prev: Optional[dict[str, Any]] = None
    prev_filename: Optional[str] = None
    if not _is_missing(previous_manifest):
        prev_path = Path(previous_manifest)
        try:
            prev = _load_json(prev_path)
            prev_filename = previous_manifest_filename or prev_path.name
        except (OSError, ValueError) as e:
            click.echo(
                f"Warning: could not read previous manifest {prev_path}: {e}; "
                "treating as first publish.",
                err=True,
            )

    existing: Optional[dict[str, Any]] = None
    if not _is_missing(changes_path) and Path(changes_path).exists():
        try:
            existing = _load_json(Path(changes_path))
        except (OSError, ValueError) as e:
            click.echo(
                f"Warning: could not read changes file {changes_path}: {e}; "
                "starting a fresh history.",
                err=True,
            )

    entry = build_entry(
        new_manifest=new,
        previous_manifest=prev,
        manifest_filename=manifest_filename,
        previous_manifest_filename=prev_filename,
    )
    history = update_history(existing, entry, edition, max_entries)

    output.write_text(json.dumps(history, indent=2), encoding="utf-8")

    if entry is None:
        click.echo(
            f"No song changes for {manifest_filename}; "
            f"history unchanged ({len(history['entries'])} entries) -> {output}"
        )
    else:
        click.echo(
            f"✅ Added changelog entry for {manifest_filename}: "
            f"{entry['added_count']} added, {entry['removed_count']} removed "
            f"({len(history['entries'])} entries total) -> {output}"
        )


@click.command(name="backfill-changelog")
@global_options
@click.option(
    "--manifests-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing the edition's *.manifest.json files.",
)
@click.option("--edition", required=True, help="Edition id, e.g. 'current'.")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("changes.json"),
    help="Where to write the rebuilt changes.json.",
)
@click.option(
    "--max-entries",
    type=int,
    default=DEFAULT_MAX_ENTRIES,
    help="Maximum number of history entries to keep.",
)
def backfill_changelog(
    manifests_dir: Path,
    edition: str,
    output: Path,
    max_entries: int,
    **kwargs,
):
    """Rebuild an edition's changes.json from its historical manifests.

    Loads every ``*.manifest.json`` in the directory, keeps those whose
    ``edition.id`` matches, sorts by ``generated_at``, and diffs consecutive
    publishes to seed the history.
    """
    manifests: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(manifests_dir.glob("*.manifest.json")):
        try:
            manifests.append((path.name, _load_json(path)))
        except (OSError, ValueError) as e:
            click.echo(f"Skipping unreadable manifest {path}: {e}", err=True)

    if not manifests:
        click.echo(f"No manifests found in {manifests_dir}", err=True)
        sys.exit(1)

    history = backfill_history(manifests, edition, max_entries)
    output.write_text(json.dumps(history, indent=2), encoding="utf-8")
    click.echo(
        f"✅ Backfilled {len(history['entries'])} changelog entries for "
        f"'{edition}' from {len(manifests)} manifests -> {output}"
    )


# Convenience for callers that want an empty starting point.
__all__ = ["update_changelog", "backfill_changelog", "empty_history"]
