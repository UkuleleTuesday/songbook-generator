"""Compute a per-edition songbook changelog as an append-only history.

A songbook edition publishes a dated manifest (``content_info.file_names`` lists
the songs). The changelog records, for each publish that actually changed the
song list, which songs were ``added``/``removed`` relative to the previously
published edition.

Rather than embedding this in the (immutable) manifest, the history lives in a
stable-named ``changes.json`` per edition::

    {
      "edition": "current",
      "entries": [ <newest first> ]
    }

This module is pure (no I/O, no GCS); the CLI in ``generator/cli/changelog.py``
handles reading/writing files and the publish pipeline handles GCS transfer.
"""

from typing import Any, Optional

DEFAULT_MAX_ENTRIES = 50


def load_file_names(manifest: dict[str, Any]) -> list[str]:
    """Safely read the list of song file names from a manifest dict."""
    return manifest.get("content_info", {}).get("file_names", []) or []


def manifest_edition_id(manifest: dict[str, Any]) -> Optional[str]:
    """Return the manifest's ``edition.id`` if present."""
    return manifest.get("edition", {}).get("id")


def diff_songs(
    new_names: list[str], old_names: list[str]
) -> tuple[list[str], list[str]]:
    """Return ``(added, removed)`` sorted song lists comparing new vs. old."""
    old_set = set(old_names)
    new_set = set(new_names)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    return added, removed


def build_entry(
    new_manifest: dict[str, Any],
    previous_manifest: Optional[dict[str, Any]],
    manifest_filename: str,
    previous_manifest_filename: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Build a single changelog entry, or ``None`` if there is nothing to record.

    Returns ``None`` when there is no previous manifest (first publish) or when
    the song list is unchanged. Skipping the empty case is what makes no-op
    re-publishes (e.g. the Tuesday cron plus a same-day config-change deploy)
    leave the history untouched instead of blanking out the last real change.
    """
    if previous_manifest is None:
        return None

    added, removed = diff_songs(
        load_file_names(new_manifest), load_file_names(previous_manifest)
    )
    if not added and not removed:
        return None

    return {
        "generated_at": new_manifest.get("generated_at"),
        "manifest_filename": manifest_filename,
        "previous_manifest": previous_manifest_filename,
        "previous_generated_at": previous_manifest.get("generated_at"),
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }


def empty_history(edition: str) -> dict[str, Any]:
    """Return a fresh, empty history document for an edition."""
    return {"edition": edition, "entries": []}


def update_history(
    existing: Optional[dict[str, Any]],
    entry: Optional[dict[str, Any]],
    edition: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Return the history with ``entry`` prepended (newest first).

    ``existing`` of ``None`` starts a fresh history. ``entry`` of ``None``
    (no change to record) returns the history unchanged. Any existing entry with
    the same ``manifest_filename`` is dropped first, so re-running a publish for
    the same dated manifest is idempotent rather than producing duplicates. The
    history is truncated to ``max_entries``.
    """
    history = (
        empty_history(edition)
        if existing is None
        else {
            "edition": existing.get("edition", edition),
            "entries": list(existing.get("entries", [])),
        }
    )

    if entry is None:
        return history

    filename = entry.get("manifest_filename")
    entries = [e for e in history["entries"] if e.get("manifest_filename") != filename]
    entries.insert(0, entry)
    history["entries"] = entries[:max_entries]
    return history


def backfill_history(
    manifests: list[tuple[str, dict[str, Any]]],
    edition: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Build a full history from a set of ``(filename, manifest)`` pairs.

    Manifests are filtered to those whose ``edition.id`` matches ``edition``
    (dropping stray objects that happen to share the bucket prefix), sorted
    ascending by ``generated_at``, then each consecutive pair is diffed. Empty
    diffs are skipped. The result is newest-first, capped at ``max_entries``.
    """
    matching = [(name, m) for name, m in manifests if manifest_edition_id(m) == edition]
    matching.sort(key=lambda nm: nm[1].get("generated_at") or "")

    history = empty_history(edition)
    previous_name: Optional[str] = None
    previous_manifest: Optional[dict[str, Any]] = None
    for name, manifest in matching:
        entry = build_entry(
            new_manifest=manifest,
            previous_manifest=previous_manifest,
            manifest_filename=name,
            previous_manifest_filename=previous_name,
        )
        history = update_history(history, entry, edition, max_entries)
        previous_name, previous_manifest = name, manifest

    return history
