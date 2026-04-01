"""Shared utilities for Drive and Drive Activity API access."""

import re
import time
from typing import Optional

import click
from google.auth import default, impersonated_credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

FOLDER_ID_APPROVED = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"
FOLDER_ID_READY_TO_PLAY = "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM"
FOLDER_ID_READY_FOR_REVIEW = "1RwcX_OnK_REqPd5hBCg3xF4JKte9rMMa"
FOLDER_ID_BEGIN_HERE = "15GFK0QgzSECDQ1hFs8wjS8yOrkTrRv3m"

FOLDER_TAG = {
    FOLDER_ID_APPROVED: "approved_date",
    FOLDER_ID_READY_TO_PLAY: "ready_to_play_date",
}

KNOWN_FOLDERS = {
    FOLDER_ID_APPROVED: "APPROVED",
    FOLDER_ID_READY_TO_PLAY: "READY_TO_PLAY",
    FOLDER_ID_READY_FOR_REVIEW: "READY_FOR_REVIEW",
    FOLDER_ID_BEGIN_HERE: "BEGIN_HERE",
}

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata",
    "https://www.googleapis.com/auth/drive.activity.readonly",
]


@retry(
    retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
    wait=wait_exponential(multiplier=1, min=5, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _query_with_retry(activity_service, body):
    return activity_service.activity().query(body=body).execute()


def authenticate(impersonate: Optional[str] = None):
    source_creds, _ = default(scopes=SCOPES)
    if impersonate:
        creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=impersonate,
            target_scopes=SCOPES,
        )
    else:
        creds = source_creds
    drive = build("drive", "v3", credentials=creds)
    activity_service = build("driveactivity", "v2", credentials=creds)
    return drive, activity_service


def fetch_songs(drive) -> list[dict]:
    """Fetch all songs from APPROVED and READY_TO_PLAY folders."""
    query = (
        f"('{FOLDER_ID_APPROVED}' in parents or '{FOLDER_ID_READY_TO_PLAY}' in parents)"
        " and trashed = false"
    )
    files = []
    page_token = None
    while True:
        resp = (
            drive.files()
            .list(
                q=query,
                pageSize=1000,
                fields="nextPageToken, files(id,name,parents,properties)",
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def get_move_events(activity_service, file_id: str) -> list[dict]:
    """
    Return all MOVE events for a file as a list of dicts:
      {"timestamp": "...", "added": ["items/<id>", ...], "removed": ["items/<id>", ...]}
    Sorted oldest-first.
    """
    events = []
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
        except Exception as e:
            click.echo(f"  Failed after retries for {file_id}: {e}", err=True)
            return []

        for activity in resp.get("activities", []):
            ts = activity.get("timestamp")
            if not ts:
                continue
            for action in activity.get("actions", []):
                move = action.get("detail", {}).get("move", {})
                added = [p.get("driveItem", {}).get("name", "") for p in move.get("addedParents", [])]
                removed = [p.get("driveItem", {}).get("name", "") for p in move.get("removedParents", [])]
                if added or removed:
                    events.append({
                        "timestamp": normalise_timestamp(ts),
                        "added": added,
                        "removed": removed,
                    })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    events.sort(key=lambda e: e["timestamp"])
    return events


def get_first_move_timestamp(activity_service, file_id: str, folder_id: str) -> Optional[str]:
    """Return the earliest timestamp of a MOVE into folder_id, or None."""
    target = f"items/{folder_id}"
    for event in get_move_events(activity_service, file_id):
        if target in event["added"]:
            return event["timestamp"]
    return None


def normalise_timestamp(ts: str) -> str:
    """Strip sub-second precision and ensure UTC Z suffix: 2022-04-05T16:13:58Z"""
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", ts)
    if match:
        return match.group(1) + "Z"
    return ts
