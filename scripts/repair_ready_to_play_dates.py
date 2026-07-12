#!/usr/bin/env python3
"""Repair the corrupted ``ready_to_play_date`` batch in Firestore (issue #442).

On 2026-06-19 (09:49-10:06 UTC) a ``tags update`` sweep stamped
``ready_to_play_date`` on ~108 song sheets with the *migration* timestamp
instead of the real "entered rotation" date. Because the tag is
``only_if_unset=True`` the wrong value is frozen in the Firestore
``song-metadata`` collection (the default read+write path; Drive writes are off,
per #281/#402).

This one-off script reads the corrupt set from Firestore, re-derives the real
date from the Drive Activity API (the first MOVE into the Ready-To-Play folder),
and — only with ``--apply`` — overwrites it in Firestore. It never writes to
Drive.

How the new value is chosen:
    Use the Activity-API move date when it is on or before the legacy ``date``
    (the first-played date) — ready-to-play must precede first-play, so that is
    the valid case. A move date *after* first-play is impossible and treated as a
    bulk folder-migration artifact, falling back to the legacy ``date``; if there
    is no legacy date either, the value becomes "unknown".

Dry-run is the default. Usage::

    uv run python scripts/repair_ready_to_play_dates.py --dry-run --output /tmp/repair.csv
    uv run python scripts/repair_ready_to_play_dates.py --apply --database pr-test
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from typing import Optional

import click

from _drive_activity import (
    FOLDER_ID_READY_TO_PLAY,
    build_activity_service,
    get_first_move_timestamp,
)
from generator.common.config import get_settings
from generator.common.metadata_store import get_metadata_store

UNKNOWN = "unknown"


def parse_legacy_date(date_str: Optional[str]) -> Optional[str]:
    """Convert a legacy ``YYYYMMDD`` date to ISO midnight UTC, or None."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (``...Z``) to an aware datetime, or None."""
    if not value or value == UNKNOWN:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_corrupt(value: Optional[str], start: datetime, end: datetime) -> bool:
    """True if ``value`` is a timestamp within ``[start, end)`` (the bad window)."""
    dt = parse_iso(value)
    return dt is not None and start <= dt < end


def choose_new_value(
    move_ts: Optional[str], legacy_date_raw: Optional[str]
) -> tuple[str, str]:
    """Pick the repaired value and its source label.

    ``date`` (legacy) is the date a song was *first played*; ``ready_to_play_date``
    is when it entered the Ready-To-Play folder. A song must become ready to play
    on or before it is first played, so a derived move date that is **after** the
    legacy first-played date is impossible — it is a bulk folder-migration
    artifact, and we fall back to the legacy date. A move date on or before the
    first-played date is kept (that is the whole point of the separate field).
    """
    legacy_iso = parse_legacy_date(legacy_date_raw)
    if move_ts:
        # Compare at day granularity: legacy dates are day-precise (midnight UTC).
        if legacy_iso is None or move_ts[:10] <= legacy_iso[:10]:
            return move_ts, "activity"
        return legacy_iso, "legacy-date"
    if legacy_iso:
        return legacy_iso, "legacy-date"
    return UNKNOWN, "unknown"


def find_corrupt_docs(
    docs: dict, field: str, start: datetime, end: datetime
) -> list[tuple[str, dict, str]]:
    """Return ``(file_id, doc, current_value)`` for docs corrupt in ``field``."""
    corrupt = []
    for file_id, doc in docs.items():
        value = (doc.get("properties") or {}).get(field)
        if is_corrupt(value, start, end):
            corrupt.append((file_id, doc, value))
    corrupt.sort(key=lambda t: (t[1].get("gdrive_file_name") or "").lower())
    return corrupt


def _delta_days(new_value: str, legacy_iso: Optional[str]) -> Optional[int]:
    a, b = parse_iso(new_value), parse_iso(legacy_iso)
    if a is None or b is None:
        return None
    return abs((a - b).days)


def _window(
    corrupt_date: Optional[str], corrupt_from: Optional[str], corrupt_to: Optional[str]
):
    """Resolve the corruption window from the CLI options."""
    if corrupt_from or corrupt_to:
        if not (corrupt_from and corrupt_to):
            raise click.UsageError(
                "--corrupt-from and --corrupt-to must be given together."
            )
        start = parse_iso(corrupt_from)
        end = parse_iso(corrupt_to)
        if start is None or end is None:
            raise click.UsageError(
                "--corrupt-from/--corrupt-to must be ISO-8601 (e.g. 2026-06-19T09:00:00Z)."
            )
        return start, end
    try:
        day = datetime.strptime(corrupt_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise click.UsageError(f"--corrupt-date must be YYYY-MM-DD: {e}")
    return day, day + timedelta(days=1)


@click.command()
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Write repairs to Firestore (default: dry-run only).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Force read-only mode (the default); overrides --apply as a safety switch.",
)
@click.option(
    "--corrupt-date",
    default="2026-06-19",
    show_default=True,
    help="Single UTC day whose values are treated as corrupt (YYYY-MM-DD).",
)
@click.option(
    "--corrupt-from",
    default=None,
    help="Start of the corrupt window, ISO-8601 (use with --corrupt-to).",
)
@click.option(
    "--corrupt-to",
    default=None,
    help="End (exclusive) of the corrupt window, ISO-8601.",
)
@click.option(
    "--field",
    default="ready_to_play_date",
    show_default=True,
    help="Metadata property to repair.",
)
@click.option(
    "--database",
    default=None,
    help="Target Firestore database (e.g. 'pr-test'); defaults to the configured DB.",
)
@click.option(
    "--impersonate-service-account",
    "impersonate",
    default=None,
    metavar="EMAIL",
    help="Service account to impersonate for the Drive Activity API.",
)
@click.option(
    "--output",
    "output_file",
    default=None,
    metavar="CSV",
    help="Write the full per-song report to this CSV file.",
)
def repair(
    apply_changes,
    dry_run,
    corrupt_date,
    corrupt_from,
    corrupt_to,
    field,
    database,
    impersonate,
    output_file,
):
    """Re-derive and (with --apply) overwrite corrupted date tags in Firestore."""
    if dry_run:
        apply_changes = False
    start, end = _window(corrupt_date, corrupt_from, corrupt_to)
    click.echo(
        f"Corrupt window: [{start.isoformat()}, {end.isoformat()})  field={field}"
    )

    if impersonate is None:
        cred = get_settings().google_cloud.credentials.get("songbook-cache-updater")
        impersonate = cred.principal if cred else None

    store = get_metadata_store(database=database)
    click.echo(f"Reading Firestore collection '{store.collection}'...")
    docs = store.get_all()
    click.echo(f"Loaded {len(docs)} documents.")

    corrupt = find_corrupt_docs(docs, field, start, end)
    click.echo(f"Found {len(corrupt)} corrupt '{field}' value(s) in the window.")
    if not corrupt:
        click.echo("Nothing to repair.")
        return
    if not 100 <= len(corrupt) <= 120:
        click.secho(
            f"WARNING: expected ~108 corrupt songs (#442), got {len(corrupt)}. "
            "Double-check the --corrupt-date/window before applying.",
            fg="yellow",
        )

    click.echo("Building Drive Activity API client...")
    activity = build_activity_service(target_principal=impersonate)

    rows = []
    counts = {"activity": 0, "legacy-date": 0, "unknown": 0}
    flags = 0
    for file_id, doc, current in corrupt:
        name = doc.get("gdrive_file_name") or file_id
        props = doc.get("properties") or {}
        legacy_raw = props.get("date")
        legacy_iso = parse_legacy_date(legacy_raw)

        move_ts = get_first_move_timestamp(activity, file_id, FOLDER_ID_READY_TO_PLAY)
        new_value, source = choose_new_value(move_ts, legacy_raw)
        counts[source] += 1

        delta = _delta_days(new_value, legacy_iso)
        flag = ""
        if move_ts and source == "legacy-date":
            # Derived move date was after the first-played date (impossible),
            # so it was rejected as a bulk-migration artifact.
            flag = f"move-after-played({move_ts[:10]}>{legacy_iso[:10]})"
        elif source == "unknown":
            flag = "no-signal"
        if flag:
            flags += 1

        rows.append(
            {
                "song": name,
                "file_id": file_id,
                "current": current,
                "proposed": new_value,
                "source": source,
                "legacy_date": legacy_raw or "",
                "delta_days": "" if delta is None else delta,
                "flag": flag,
            }
        )
        marker = f"  [{flag}]" if flag else ""
        click.echo(f"  {name}: {current} -> {new_value}  ({source}){marker}")

    click.echo(
        f"\nSummary: found {len(corrupt)}; "
        f"via-activity {counts['activity']}; "
        f"via-legacy {counts['legacy-date']}; "
        f"unknown {counts['unknown']}; flagged {flags}."
    )

    if output_file:
        with open(output_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "song",
                    "file_id",
                    "current",
                    "proposed",
                    "source",
                    "legacy_date",
                    "delta_days",
                    "flag",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        click.echo(f"Wrote report to {output_file}")

    if not apply_changes:
        click.echo("\nDRY RUN — no changes written. Re-run with --apply to write.")
        return

    click.echo(f"\nApplying {len(rows)} repair(s) to Firestore...")
    written = 0
    for row, (file_id, doc, _current) in zip(rows, corrupt):
        store.write(file_id, {field: row["proposed"]}, name=doc.get("gdrive_file_name"))
        written += 1
    click.echo(f"Wrote {written} document(s) to collection '{store.collection}'.")


if __name__ == "__main__":
    repair()
