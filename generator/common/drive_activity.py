"""Shared Drive Activity API helpers for reconstructing folder-move history."""

from __future__ import annotations

import re

import click
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..worker.gcp import get_credentials

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
]


def build_activity_service(target_principal: str | None = None):
    """Build a Drive Activity API v2 client using the repo credential helper."""
    creds = get_credentials(scopes=SCOPES, target_principal=target_principal)
    return build("driveactivity", "v2", credentials=creds)


@retry(
    retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
    wait=wait_exponential(multiplier=1, min=5, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _query_with_retry(activity_service, body):
    return activity_service.activity().query(body=body).execute()


def normalise_timestamp(ts: str) -> str:
    """Strip sub-second precision and force a trailing Z: 2022-04-05T16:13:58Z."""
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", ts)
    if match:
        return match.group(1) + "Z"
    return ts


def get_move_events(activity_service, file_id: str) -> list[dict]:
    """Return every MOVE event for ``file_id`` as dicts, sorted oldest-first.

    Each dict is ``{"timestamp": ..., "added": [...], "removed": [...]}`` where
    the parent lists hold Drive Activity item names like ``items/<folder_id>``.
    On any API error this fails soft and returns ``[]``.
    """
    events: list[dict] = []
    page_token = None

    while True:
        body = {
            "itemName": f"items/{file_id}",
            "filter": "detail.action_detail_case:MOVE",
            "pageSize": 100,
        }
        if page_token:
            body["pageToken"] = page_token

        try:
            resp = _query_with_retry(activity_service, body)
        except HttpError as e:
            click.echo(f"  Activity API error for {file_id}: {e}", err=True)
            return []
        except Exception as e:  # noqa: BLE001 - network failure path, fail soft
            click.echo(f"  Failed after retries for {file_id}: {e}", err=True)
            return []

        for activity in resp.get("activities", []):
            ts = activity.get("timestamp")
            if not ts:
                continue
            for action in activity.get("actions", []):
                move = action.get("detail", {}).get("move", {})
                added = [
                    p.get("driveItem", {}).get("name", "")
                    for p in move.get("addedParents", [])
                ]
                removed = [
                    p.get("driveItem", {}).get("name", "")
                    for p in move.get("removedParents", [])
                ]
                if added or removed:
                    events.append(
                        {
                            "timestamp": normalise_timestamp(ts),
                            "added": added,
                            "removed": removed,
                        }
                    )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    events.sort(key=lambda e: e["timestamp"])
    return events


def get_first_move_timestamp(
    activity_service, file_id: str, folder_id: str
) -> str | None:
    """Return the earliest timestamp of a MOVE into ``folder_id``, or None."""
    target = f"items/{folder_id}"
    for event in get_move_events(activity_service, file_id):
        if target in event["added"]:
            return event["timestamp"]
    return None
