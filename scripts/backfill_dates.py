#!/usr/bin/env python3
"""Backfill approved_date and ready_to_play_date from Drive Activity API."""

from typing import Optional

import click

from _drive_activity import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    FOLDER_TAG,
    authenticate,
    fetch_songs,
    get_first_move_timestamp,
)


def write_property(drive, file_id: str, key: str, value: str):
    current = (
        drive.files().get(fileId=file_id, fields="properties").execute().get("properties", {})
    )
    current[key] = value
    drive.files().update(fileId=file_id, body={"properties": current}, fields="properties").execute()


@click.command()
@click.option("--dry-run", is_flag=True)
@click.option("--impersonate-service-account", default=None, metavar="EMAIL")
@click.option("--set-sentinel", is_flag=True, help="Write 'unknown' for songs with no MOVE event.")
@click.option("--approved-only", is_flag=True)
@click.option("--ready-to-play-only", is_flag=True)
def backfill_dates(dry_run: bool, impersonate_service_account: Optional[str], set_sentinel: bool, approved_only: bool, ready_to_play_only: bool):
    """Backfill approved_date and ready_to_play_date from Drive Activity API."""
    click.echo("Authenticating...")
    drive, activity_service = authenticate(impersonate=impersonate_service_account)

    click.echo("Fetching songs...")
    all_songs = fetch_songs(drive)
    click.echo(f"Found {len(all_songs)} songs.")

    folder_filter = None
    if approved_only:
        folder_filter = FOLDER_ID_APPROVED
    elif ready_to_play_only:
        folder_filter = FOLDER_ID_READY_TO_PLAY

    candidates = []
    for song in all_songs:
        props = song.get("properties", {})
        parents = song.get("parents", [])
        if folder_filter is not None and folder_filter not in parents:
            continue
        for folder_id, tag_name in FOLDER_TAG.items():
            if tag_name not in props:
                candidates.append((song, folder_id, tag_name))

    click.echo(f"{len(candidates)} songs missing a date tag.\n")

    backfilled = 0
    unmatched = []
    errors = 0

    for song, folder_id, tag_name in candidates:
        name = song["name"]
        file_id = song["id"]
        click.echo(f"Processing: {name}")

        try:
            ts = get_first_move_timestamp(activity_service, file_id, folder_id)
        except Exception as e:
            click.echo(f"  ERROR: {e}", err=True)
            errors += 1
            continue

        if ts:
            click.echo(f"  {tag_name} = {ts}")
            if dry_run:
                click.echo("  DRY RUN: skipping write.")
            else:
                write_property(drive, file_id, tag_name, ts)
                click.echo("  Written.")
            backfilled += 1
        else:
            click.echo("  UNMATCHED: no MOVE event into target folder.")
            unmatched.append((name, file_id, tag_name))
            if set_sentinel and not dry_run:
                write_property(drive, file_id, tag_name, "unknown")
                click.echo("  Wrote sentinel 'unknown'.")
            elif set_sentinel and dry_run:
                click.echo("  DRY RUN: would write sentinel 'unknown'.")

    click.echo("\n" + "=" * 50)
    click.echo(f"Total: {len(candidates)}, Backfilled: {backfilled}, Unmatched: {len(unmatched)}, Errors: {errors}")
    if dry_run:
        click.echo("DRY RUN — no changes written.")
    if unmatched:
        click.echo("\nUNMATCHED:")
        for name, file_id, tag_name in unmatched:
            click.echo(f"  [{tag_name}] {name} ({file_id})")


if __name__ == "__main__":
    backfill_dates()
