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

from .common.titles import generate_short_title

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


def compose_entries(base: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    """Fold two chained entries into one cumulative entry.

    ``base`` records ``B -> M`` and ``step`` records ``M -> F`` (``step``'s
    ``previous_manifest`` is ``base``'s ``manifest_filename``). The result records
    the net ``B -> F`` change: it keeps ``step``'s identity (filename/timestamp)
    but adopts ``base``'s baseline (``previous_*``). Songs added then removed (or
    removed then re-added) across the two steps cancel out, so the cumulative diff
    reflects the endpoints only.

    This is what lets several same-day publishes — which all overwrite the one
    date-stamped artifact — collapse into a single entry for it, instead of a
    later publish evicting an earlier one's changes.
    """
    a1, r1 = set(base.get("added", [])), set(base.get("removed", []))
    a2, r2 = set(step.get("added", [])), set(step.get("removed", []))
    added = sorted((a1 - r2) | (a2 - r1))
    removed = sorted((r1 - a2) | (r2 - a1))
    return {
        **step,
        "previous_manifest": base.get("previous_manifest"),
        "previous_generated_at": base.get("previous_generated_at"),
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }


def update_history(
    existing: Optional[dict[str, Any]],
    entry: Optional[dict[str, Any]],
    edition: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Return the history with ``entry`` prepended (newest first).

    ``existing`` of ``None`` starts a fresh history. ``entry`` of ``None``
    (no change to record) returns the history unchanged.

    Any existing entry with the same ``manifest_filename`` is replaced (not
    duplicated), which keeps re-running a publish idempotent. When the new entry
    *chains onto* that existing one — i.e. it was diffed against the very manifest
    the existing entry produced (``entry['previous_manifest']`` equals the
    existing entry's ``manifest_filename``) — the two are folded into a single
    cumulative entry via :func:`compose_entries`. That is the same-day case: the
    date-stamped artifact is published more than once on one UTC day, each publish
    diffing against the previous, and we want the one entry for that date to carry
    the whole day's net change rather than only the last publish's slice. The
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
    prior = next(
        (e for e in history["entries"] if e.get("manifest_filename") == filename),
        None,
    )
    if prior is not None and entry.get("previous_manifest") == prior.get(
        "manifest_filename"
    ):
        entry = compose_entries(prior, entry)

    entries = [e for e in history["entries"] if e.get("manifest_filename") != filename]
    entries.insert(0, entry)
    history["entries"] = entries[:max_entries]
    return history


def short_key(raw: str, max_length: Optional[int] = None) -> str:
    """Canonical, comparison-friendly form of a song title.

    Runs the title through the same deterministic shortener the TOC uses
    (:func:`generate_short_title`) and casefolds it, so a manifest's full
    ``file_names`` entry and the (already shortened) title parsed from a rendered
    TOC page collapse to the same key. This is what lets the changelog diff span
    the manifest era and the TOC-reconstructed era without spurious churn.
    """
    title = generate_short_title(raw or "", max_length=max_length)
    if title.endswith("*"):
        title = title[:-1].rstrip()
    return title.casefold()


def canon(raw: str) -> str:
    """Truncation-insensitive canonical form of a song title for matching.

    Normalizes via :func:`generate_short_title` (drops ``feat.``/version parens
    the TOC also dropped, *no* truncation), strips trailing decorations
    (``*``/ellipsis/whitespace), and casefolds. Used as a prefix-matching anchor
    so a song renders to the same canonical regardless of how a given TOC era
    truncated or decorated it.
    """
    s = generate_short_title(raw or "", max_length=None).strip()
    changed = True
    while changed:
        changed = False
        for suffix in ("...", "…", "*"):
            if s.endswith(suffix):
                s = s[: -len(suffix)].rstrip()
                changed = True
    return " ".join(s.split()).casefold()


def build_vocabulary(names: list[str]) -> dict[str, str]:
    """Map ``canon(name) -> name`` for a reference catalogue of full song names."""
    return {canon(n): n for n in names if canon(n)}


def resolve(
    stem: str, vocabulary: dict[str, str], min_overlap: int = 6
) -> Optional[str]:
    """Resolve a (possibly truncated/glued) TOC title to a catalogue full name.

    Matches when ``canon(stem)`` and a vocabulary key are prefix-compatible (one
    is a prefix of the other) — exactly how the drifting renders relate:
    truncation makes the TOC string a prefix of the real name; a glued page number
    makes the real name a prefix of the TOC string. Prefers an exact hit, else the
    longest overlap (deterministic tiebreak). Returns ``None`` when nothing clears
    ``min_overlap`` (e.g. a song that predates the catalogue).
    """
    key = canon(stem)
    if not key:
        return None
    if key in vocabulary:
        return vocabulary[key]
    best: Optional[str] = None
    best_overlap = -1
    for vkey, name in vocabulary.items():
        if vkey.startswith(key) or key.startswith(vkey):
            overlap = min(len(vkey), len(key))
            if overlap > best_overlap or (overlap == best_overlap and name < best):
                best, best_overlap = name, overlap
    return best if best_overlap >= min_overlap else None


def diff_keyed(new: dict[str, str], old: dict[str, str]) -> tuple[list[str], list[str]]:
    """Diff two ``{key: label}`` song maps, returning sorted added/removed labels.

    Comparison is on the canonical keys; the human-readable labels come from the
    side that holds the song (added → ``new``, removed → ``old``), so recent
    entries keep full names while historical ones use the shortened TOC titles.
    """
    added_keys, removed_keys = diff_songs(list(new), list(old))
    added = sorted(new[k] for k in added_keys)
    removed = sorted(old[k] for k in removed_keys)
    return added, removed


def build_timeline(
    publishes: list[dict[str, Any]],
    edition: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Build a full ``changes.json`` from a list of publishes (newest first).

    Each publish is ``{"date", "source", "filename", "songs": {key: label}}``.
    Publishes are ordered by date, consecutive song sets are diffed (empty diffs
    skipped), and each recorded entry is tagged with its ``source``
    (``"manifest"`` or ``"toc-page"``). Unlike :func:`update_history` (which
    merges one new publish at a time), this rebuilds the whole history at once.
    """
    pubs = sorted(publishes, key=lambda p: p["date"])
    entries: list[dict[str, Any]] = []
    previous: Optional[dict[str, Any]] = None
    for pub in pubs:
        if previous is not None:
            added, removed = diff_keyed(pub["songs"], previous["songs"])
            if added or removed:
                entries.append(
                    {
                        "generated_at": pub.get("generated_at", pub["date"]),
                        "date": pub["date"],
                        "source": pub["source"],
                        "filename": pub["filename"],
                        "previous_filename": previous["filename"],
                        "previous_date": previous["date"],
                        "added": added,
                        "removed": removed,
                        "added_count": len(added),
                        "removed_count": len(removed),
                    }
                )
        previous = pub
    entries.reverse()  # newest first
    return {"edition": edition, "entries": entries[:max_entries]}


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
