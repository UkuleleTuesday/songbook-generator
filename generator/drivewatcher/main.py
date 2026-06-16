"""
Google Drive change detection service (push-based consumer).

This module processes Drive push notifications published by the
drivewebhook HTTP function.  On each Pub/Sub message it calls
changes.list to resolve the actual file changes, filters them to
the configured watched folders, and publishes the results to the
existing DRIVE_CHANGES_PUBSUB_TOPIC so that downstream consumers
(e.g. tagupdater) require no changes.
"""

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Optional, Tuple

import click
from cloudevents.http import CloudEvent
from google.auth import default
from google.cloud import pubsub_v1, storage
from googleapiclient.discovery import build

from ..common.config import get_settings
from ..common.tracing import get_tracer, setup_tracing
from ..worker.gcp import get_credentials
from .watch import get_page_token, save_page_token


@lru_cache(maxsize=1)
def _get_services() -> dict:
    """Initialize services for the drive watcher consumer."""
    settings = get_settings()

    _, project_id = default()
    if project_id:
        os.environ["GCP_PROJECT_ID"] = project_id
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

    cache_updater_creds_config = settings.google_cloud.credentials.get(
        "songbook-cache-updater"
    )
    if not cache_updater_creds_config:
        raise RuntimeError("Credential config 'songbook-cache-updater' not found.")

    creds = get_credentials(
        scopes=cache_updater_creds_config.scopes,
        target_principal=cache_updater_creds_config.principal,
    )

    service_name = os.environ.get("K_SERVICE", "songbook-generator-drivewatcher")
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    drive_service = build("drive", "v3", credentials=creds)
    storage_client = storage.Client(project=project_id)

    publisher = pubsub_v1.PublisherClient()
    drive_changes_topic = os.environ.get(
        "DRIVE_CHANGES_PUBSUB_TOPIC", "songbook-drive-changes"
    )
    topic_path = publisher.topic_path(project_id, drive_changes_topic)

    return {
        "tracer": tracer,
        "drive": drive_service,
        "publisher": publisher,
        "topic_path": topic_path,
        "storage_client": storage_client,
        "project_id": project_id,
    }


def _get_watched_folders() -> List[str]:
    """Return the list of folder IDs to watch for changes."""
    folder_ids_env = os.environ.get("DRIVE_WATCHED_FOLDERS")
    if folder_ids_env:
        return [f.strip() for f in folder_ids_env.split(",") if f.strip()]
    settings = get_settings()
    return settings.song_sheets.folder_ids


def _fetch_changes(services: dict, page_token: str) -> Tuple[List[dict], str]:
    """
    Fetch all pending changes from the Drive changes.list API.

    Paginates until a newStartPageToken is returned, then yields
    that token as the updated cursor.  Returns (changes, new_token).
    """
    all_changes: List[dict] = []
    current_token: Optional[str] = page_token

    while current_token:
        response = (
            services["drive"]
            .changes()
            .list(
                pageToken=current_token,
                fields=(
                    "nextPageToken,newStartPageToken,"
                    "changes("
                    "changeType,removed,fileId,"
                    "file(id,name,parents,trashed,mimeType,properties)"
                    ")"
                ),
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                spaces="drive",
            )
            .execute()
        )

        all_changes.extend(response.get("changes", []))

        if "nextPageToken" in response:
            current_token = response["nextPageToken"]
        elif "newStartPageToken" in response:
            return all_changes, response["newStartPageToken"]
        else:
            break

    return all_changes, page_token


def _filter_changes_by_folders(
    changes: List[dict], watched_folders: List[str]
) -> List[dict]:
    """
    Filter Drive changes to files whose direct parent is a watched folder.

    Returns a list of file-info dicts that match the existing Pub/Sub
    message format expected by downstream consumers (e.g. tagupdater).
    """
    filtered: List[dict] = []

    for change in changes:
        if change.get("changeType") != "file":
            continue

        file_data = change.get("file")
        if not file_data:
            continue

        if file_data.get("trashed"):
            continue

        parents = file_data.get("parents", [])
        parent_folder = next((p for p in parents if p in watched_folders), None)
        if parent_folder is None:
            continue

        filtered.append(
            {
                "id": file_data["id"],
                "name": file_data.get("name", ""),
                "folder_id": parent_folder,
                "mime_type": file_data.get("mimeType"),
                "parents": parents,
                "properties": file_data.get("properties", {}),
            }
        )

    return filtered


def _publish_changes(
    services: dict, changed_files: List[dict], check_time: datetime
) -> None:
    """Publish change notifications to the Pub/Sub topic."""
    if not changed_files:
        return

    with services["tracer"].start_as_current_span(
        "publish_change_notifications"
    ) as span:
        message_data = {
            "check_time": check_time.isoformat(),
            "changed_files": changed_files,
            "file_count": len(changed_files),
            "folders_checked": _get_watched_folders(),
        }

        serialized_message = json.dumps(message_data)

        click.echo(f"Publishing change notification to {services['topic_path']}")
        future = services["publisher"].publish(
            services["topic_path"],
            serialized_message.encode("utf-8"),
            source="drivewatcher",
            change_count=str(len(changed_files)),
        )
        future.result()

        span.set_attribute("message_size", len(serialized_message))
        span.set_attribute("published_files_count", len(changed_files))

        click.echo(
            f"Successfully published notification for "
            f"{len(changed_files)} changed files"
        )


def drivewatcher_main(cloud_event: CloudEvent) -> None:
    """
    Cloud Function entry point for Drive change processing.

    Triggered by Pub/Sub messages from the drivewebhook HTTP function.
    Calls changes.list to resolve actual file changes, filters them to
    the configured folder IDs, and publishes to DRIVE_CHANGES_PUBSUB_TOPIC.
    """
    services = _get_services()

    with services["tracer"].start_as_current_span("drivewatcher_main") as main_span:
        current_time = datetime.now(timezone.utc)
        main_span.set_attribute("check_time", current_time.isoformat())

        watched_folders = _get_watched_folders()
        if not watched_folders:
            click.echo("No folders configured to watch", err=True)
            main_span.set_attribute("status", "failed_no_folders")
            return

        main_span.set_attribute("watched_folders", ",".join(watched_folders))

        page_token = get_page_token(services)
        if not page_token:
            click.echo(
                "No page token stored; skipping (watch not initialized)",
                err=True,
            )
            main_span.set_attribute("status", "no_page_token")
            return

        raw_changes, new_page_token = _fetch_changes(services, page_token)
        changed_files = _filter_changes_by_folders(raw_changes, watched_folders)

        main_span.set_attribute("raw_changes_count", len(raw_changes))
        main_span.set_attribute("filtered_changes_count", len(changed_files))

        if changed_files:
            _publish_changes(services, changed_files, current_time)
            main_span.set_attribute("status", "published_changes")
        else:
            main_span.set_attribute("status", "no_relevant_changes")

        save_page_token(services, new_page_token)
        click.echo("Drive watcher completed successfully")
