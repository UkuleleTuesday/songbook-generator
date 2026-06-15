import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import click

from ..changelog import (
    DEFAULT_MAX_ENTRIES,
    backfill_history,
    build_entry,
    build_timeline,
    empty_history,
    short_key,
    update_history,
)
from .utils import global_options

# ukulele-tuesday-songbook-<edition>-YYYY-MM-DD(.pdf | .manifest.json)
# Edition ids can contain hyphens, so the date anchors the split.
_NAME_RE = re.compile(
    r"^ukulele-tuesday-songbook-(?P<edition>.+)-(?P<date>\d{4}-\d{2}-\d{2})"
    r"\.(?:pdf|manifest\.json)$"
)


def _parse_edition_date(filename: str) -> Optional[tuple[str, str]]:
    """Return ``(edition, YYYY-MM-DD)`` parsed from a songbook filename, or None."""
    m = _NAME_RE.match(filename)
    return (m.group("edition"), m.group("date")) if m else None


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


@click.command(name="backfill-changelog-from-pdfs")
@global_options
@click.option(
    "--pdfs-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory of historical *.pdf songbooks (any path scheme, flat).",
)
@click.option(
    "--manifests-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Optional directory of *.manifest.json (preferred over PDFs per date; "
    "gives full-name labels for the manifest era).",
)
@click.option("--edition", required=True, help="Edition id, e.g. 'current'.")
@click.option(
    "--max-title-length",
    type=int,
    default=None,
    help="TOC max title length used for canonical matching "
    "(defaults to the configured Toc.max_toc_entry_length).",
)
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
def backfill_changelog_from_pdfs(
    pdfs_dir: Path,
    manifests_dir: Optional[Path],
    edition: str,
    max_title_length: Optional[int],
    output: Path,
    max_entries: int,
    **kwargs,
):
    """Rebuild a full changes.json from historical PDFs (and optional manifests).

    For dates that predate the JSON manifest, the song list is reconstructed from
    the rendered Table-of-Contents page text; for the manifest era, the manifest
    is used (preferred per date) so recent entries keep full song names. Both are
    matched on a canonical shortened-title key so the eras stitch together
    cleanly. Filenames must follow ``ukulele-tuesday-songbook-<edition>-DATE.*``.
    """
    # Lazy imports: fitz / settings are heavy and only needed here.
    import fitz

    from ..common.config import get_settings
    from ..toc_parse import parse_toc_songs

    max_len = (
        max_title_length
        if max_title_length is not None
        else get_settings().toc.max_toc_entry_length
    )

    # date -> publish record; manifests win over PDFs for the same date.
    publishes: dict[str, dict[str, Any]] = {}

    if manifests_dir:
        for path in sorted(manifests_dir.glob("*.manifest.json")):
            parsed = _parse_edition_date(path.name)
            try:
                manifest = _load_json(path)
            except (OSError, ValueError) as e:
                click.echo(f"Skipping unreadable manifest {path}: {e}", err=True)
                continue
            ed = (manifest.get("edition") or {}).get("id") or (
                parsed[0] if parsed else None
            )
            if ed != edition or not parsed:
                continue
            names = manifest.get("content_info", {}).get("file_names") or []
            publishes[parsed[1]] = {
                "date": parsed[1],
                "generated_at": manifest.get("generated_at", parsed[1]),
                "source": "manifest",
                "filename": path.name,
                "songs": {short_key(n, max_len): n for n in names},
            }

    for path in sorted(pdfs_dir.glob("*.pdf")):
        parsed = _parse_edition_date(path.name)
        if not parsed or parsed[0] != edition:
            continue
        date = parsed[1]
        if date in publishes:  # a manifest already covers this date
            continue
        try:
            with fitz.open(path) as doc:
                titles = parse_toc_songs(doc)
        except Exception as e:  # noqa: BLE001 - skip a single bad PDF, keep going
            click.echo(f"Skipping unreadable PDF {path}: {e}", err=True)
            continue
        if not titles:
            click.echo(f"No TOC songs parsed from {path.name}; skipping.", err=True)
            continue
        publishes[date] = {
            "date": date,
            "generated_at": date,
            "source": "toc-page",
            "filename": path.name,
            "songs": {short_key(t, max_len): t for t in titles},
        }

    if not publishes:
        click.echo(f"No publishes found for edition '{edition}'.", err=True)
        sys.exit(1)

    history = build_timeline(list(publishes.values()), edition, max_entries)
    output.write_text(json.dumps(history, indent=2), encoding="utf-8")
    n_manifest = sum(1 for p in publishes.values() if p["source"] == "manifest")
    n_toc = len(publishes) - n_manifest
    click.echo(
        f"✅ Backfilled {len(history['entries'])} changelog entries for "
        f"'{edition}' from {len(publishes)} publishes "
        f"({n_manifest} manifest, {n_toc} toc-page) -> {output}"
    )


# Convenience for callers that want an empty starting point.
__all__ = [
    "update_changelog",
    "backfill_changelog",
    "backfill_changelog_from_pdfs",
    "empty_history",
]
