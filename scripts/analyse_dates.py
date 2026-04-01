#!/usr/bin/env python3
"""Analyse date field vs Drive Activity API move timestamps."""

import csv
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import click

from _drive_activity import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    FOLDER_TAG,
    KNOWN_FOLDERS,
    authenticate,
    fetch_songs,
    get_move_events,
)


def _parse_date_field(date_str: str) -> Optional[str]:
    try:
        dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


@click.command()
@click.option("--impersonate-service-account", default=None, metavar="EMAIL")
@click.option("--approved-only", is_flag=True)
@click.option("--ready-to-play-only", is_flag=True)
@click.option("--output", "output_file", default=None, metavar="FILE")
def analyse_dates(impersonate_service_account: Optional[str], approved_only: bool, ready_to_play_only: bool, output_file: Optional[str]):
    """Compare date field against Drive Activity API move timestamps."""
    click.echo("Authenticating...", err=True)
    drive, activity_service = authenticate(impersonate=impersonate_service_account)

    click.echo("Fetching songs...", err=True)
    all_songs = fetch_songs(drive)

    folder_filter = None
    if approved_only:
        folder_filter = FOLDER_ID_APPROVED
    elif ready_to_play_only:
        folder_filter = FOLDER_ID_READY_TO_PLAY

    candidates = [
        (s, folder_id, tag_name)
        for s in all_songs
        for folder_id, tag_name in FOLDER_TAG.items()
        if folder_id in s.get("parents", [])
        and (folder_filter is None or folder_id == folder_filter)
    ]
    candidates.sort(key=lambda x: x[0]["name"])

    click.echo(f"Analysing {len(candidates)} songs...", err=True)

    out = open(output_file, "w") if output_file else None
    try:
        writer = csv.writer(out if out else sys.stdout)
        folder_columns = list(KNOWN_FOLDERS.values())
        writer.writerow(["song", "date_field"] + folder_columns + ["delta_days", "notes", "other_moves"])

        deltas_days = []
        no_activity = []

        for song, folder_id, tag_name in candidates:
            name = song["name"]
            file_id = song["id"]
            date_str = song.get("properties", {}).get("date", "")
            date_as_iso = _parse_date_field(date_str) if date_str else None

            time.sleep(0.7)
            events = get_move_events(activity_service, file_id)
            click.echo(f"  {name}", err=True)

            first_move_into = {}
            for e in events:
                for raw_id in e["added"]:
                    fid = raw_id.replace("items/", "")
                    if fid in KNOWN_FOLDERS and fid not in first_move_into:
                        first_move_into[fid] = e["timestamp"][:10]

            other = []
            for e in events:
                unknown_added = [i.replace("items/", "") for i in e["added"] if i.replace("items/", "") not in KNOWN_FOLDERS]
                unknown_removed = [i.replace("items/", "") for i in e["removed"] if i.replace("items/", "") not in KNOWN_FOLDERS]
                if unknown_added or unknown_removed:
                    other.append(f"{e['timestamp'][:10]} +{unknown_added} -{unknown_removed}")

            folder_values = [first_move_into.get(fid, "") for fid in KNOWN_FOLDERS]
            other_moves_str = " | ".join(other)

            target = f"items/{folder_id}"
            ts = next((e["timestamp"] for e in events if target in e["added"]), None)

            if ts and date_as_iso:
                dt_activity = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                dt_date = datetime.strptime(date_as_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                delta = abs((dt_activity - dt_date).days)
                deltas_days.append(delta)
                writer.writerow([name, date_str] + folder_values + [delta, "", other_moves_str])
            elif ts:
                writer.writerow([name, date_str] + folder_values + ["", "date unparseable", other_moves_str])
            elif not events:
                no_activity.append(name)
                writer.writerow([name, date_str] + folder_values + ["", "no MOVE events at all", other_moves_str])
            else:
                no_activity.append(name)
                writer.writerow([name, date_str] + folder_values + ["", "no MOVE into expected folder", other_moves_str])

        if out:
            out.flush()
        click.echo("", err=True)
        click.echo(f"Total: {len(candidates)}, Compared: {len(deltas_days)}, No MOVE: {len(no_activity)}", err=True)
        if deltas_days:
            click.echo(f"Delta — min: {min(deltas_days)}d, max: {max(deltas_days)}d, avg: {sum(deltas_days)/len(deltas_days):.1f}d", err=True)
    finally:
        if out:
            out.close()
            click.echo(f"Written to {output_file}", err=True)


if __name__ == "__main__":
    analyse_dates()
