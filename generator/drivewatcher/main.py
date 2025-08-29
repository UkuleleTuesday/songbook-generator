"""
Google Drive change detection service.

This module provides functionality to monitor Google Drive folders for changes
and publish notifications to a Pub/Sub topic when changes are detected.
"""

import os
import json
from datetime import datetime, timedelta
from functools import lru_cache
from typing import List, Optional

import click
from cloudevents.http import CloudEvent
from google.auth import default
from google.cloud import pubsub_v1, storage
from googleapiclient.discovery import build

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..common.caching import init_cache
from ..common.tracing import get_tracer, setup_tracing
from ..worker.gcp import get_credentials


@lru_cache(maxsize=1)
def _get_services():
    """Initialize services for the drive watcher."""
    settings = get_settings()

    # Determine project ID from default credentials
    _, project_id = default()
    if project_id:
        os.environ["GCP_PROJECT_ID"] = project_id
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

    # Get credentials for Google Drive access
    merger_credential_config = settings.google_cloud.credentials.get("songbook-merger")
    if not merger_credential_config:
        raise click.Abort("Credential config 'songbook-merger' not found.")

    merger_creds = get_credentials(
        scopes=merger_credential_config.scopes,
        target_principal=merger_credential_config.principal,
    )

    # Setup tracing
    service_name = os.environ.get("K_SERVICE", "songbook-generator-drivewatcher")
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    # Initialize Google services
    drive_service = build("drive", "v3", credentials=merger_creds)
    storage_client = storage.Client(project=project_id)

    # Initialize Pub/Sub publisher
    publisher = pubsub_v1.PublisherClient()

    # Get topic path for drive change notifications
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


def _get_last_check_time(services) -> Optional[datetime]:
    """
    Get the last time we checked for drive changes.

    This is stored as metadata in a special blob in GCS to persist
    between function invocations.
    """
    try:
        settings = get_settings()
        bucket_name = settings.caching.gcs.worker_cache_bucket
        bucket = services["storage_client"].bucket(bucket_name)

        # Use a special blob to track last check time
        blob = bucket.get_blob("drivewatcher/last-check-time.txt")
        if not blob:
            click.echo("No previous check time found. Checking last hour.")
            return datetime.utcnow() - timedelta(hours=1)

        # Read the timestamp from the blob
        timestamp_str = blob.download_as_text().strip()
        last_check_time = datetime.fromisoformat(timestamp_str)
        click.echo(f"Last check was at {last_check_time}")
        return last_check_time

    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error reading last check time: {e}")
        # Default to checking last hour if we can't read the timestamp
        return datetime.utcnow() - timedelta(hours=1)


def _save_check_time(services, check_time: datetime):
    """Save the current check time for the next run."""
    try:
        settings = get_settings()
        bucket_name = settings.caching.gcs.worker_cache_bucket
        bucket = services["storage_client"].bucket(bucket_name)

        blob = bucket.blob("drivewatcher/last-check-time.txt")
        blob.upload_from_string(check_time.isoformat(), content_type="text/plain")
        click.echo(f"Saved check time: {check_time}")

    except (OSError, ValueError) as e:
        click.echo(f"Error saving check time: {e}", err=True)


def _get_watched_folders() -> List[str]:
    """Get the list of folder IDs to watch for changes."""
    # Environment variable takes precedence for configuration
    folder_ids_env = os.environ.get("DRIVE_WATCHED_FOLDERS")
    if folder_ids_env:
        return [f.strip() for f in folder_ids_env.split(",") if f.strip()]

    # Fall back to the same folders used by the merger
    settings = get_settings()
    return settings.song_sheets.folder_ids


def _detect_changes(
    services, watched_folders: List[str], since: datetime
) -> List[dict]:
    """
    Detect changes in Google Drive folders since the given timestamp.

    Returns a list of changed file information dictionaries.
    """
    with services["tracer"].start_as_current_span("detect_drive_changes") as span:
        cache = init_cache()
        gdrive_client = GoogleDriveClient(cache=cache, drive=services["drive"])

        all_changed_files = []

        for folder_id in watched_folders:
            click.echo(f"Checking folder {folder_id} for changes since {since}")

            try:
                # Query for files modified after the since timestamp
                files = gdrive_client.query_drive_files(folder_id, modified_after=since)

                for file in files:
                    file_info = {
                        "id": file.id,
                        "name": file.name,
                        "folder_id": folder_id,
                        "mime_type": file.mimeType,
                        "parents": file.parents,
                        "properties": file.properties,
                    }
                    all_changed_files.append(file_info)
                    click.echo(f"  CHANGED: {file.name} (ID: {file.id})")

            except (OSError, ValueError) as e:
                click.echo(f"Error checking folder {folder_id}: {e}", err=True)
                span.set_attribute(f"error_folder_{folder_id}", str(e))

        span.set_attribute("changed_files_count", len(all_changed_files))
        span.set_attribute("watched_folders", ",".join(watched_folders))

        if all_changed_files:
            click.echo(f"Found {len(all_changed_files)} changed files")
        else:
            click.echo("No changes detected")

        return all_changed_files


def _publish_changes(services, changed_files: List[dict], check_time: datetime):
    """Publish change notifications to Pub/Sub topic."""
    if not changed_files:
        return

    with services["tracer"].start_as_current_span(
        "publish_change_notifications"
    ) as span:
        try:
            # Create a message with all the changes
            message_data = {
                "check_time": check_time.isoformat(),
                "changed_files": changed_files,
                "file_count": len(changed_files),
                "folders_checked": _get_watched_folders(),
            }

            # Serialize the message
            serialized_message = json.dumps(message_data)

            # Publish to Pub/Sub
            click.echo(f"Publishing change notification to {services['topic_path']}")
            future = services["publisher"].publish(
                services["topic_path"],
                serialized_message.encode("utf-8"),
                source="drivewatcher",
                change_count=str(len(changed_files)),
            )

            # Wait for the publish to complete
            future.result()

            span.set_attribute("message_size", len(serialized_message))
            span.set_attribute("published_files_count", len(changed_files))

            click.echo(
                f"Successfully published notification for {len(changed_files)} changed files"
            )

        except Exception as e:
            click.echo(f"Error publishing changes: {e}", err=True)
            span.set_attribute("publish_error", str(e))
            raise


def drivewatcher_main(cloud_event: CloudEvent):
    """
    Cloud Function entry point for Google Drive change detection.

    This function is triggered by Cloud Scheduler every minute to check
    for changes in configured Google Drive folders.
    """
    services = _get_services()

    with services["tracer"].start_as_current_span("drivewatcher_main") as main_span:
        try:
            current_time = datetime.utcnow()
            main_span.set_attribute("check_time", current_time.isoformat())

            # Get watched folders
            watched_folders = _get_watched_folders()
            if not watched_folders:
                click.echo("No folders configured to watch", err=True)
                main_span.set_attribute("status", "failed_no_folders")
                return

            main_span.set_attribute("watched_folders", ",".join(watched_folders))
            click.echo(f"Watching folders: {watched_folders}")

            # Get last check time
            last_check_time = _get_last_check_time(services)
            main_span.set_attribute("last_check_time", str(last_check_time))

            # Detect changes since last check
            changed_files = _detect_changes(services, watched_folders, last_check_time)

            # Publish changes if any found
            if changed_files:
                _publish_changes(services, changed_files, current_time)
                main_span.set_attribute("status", "published_changes")
            else:
                main_span.set_attribute("status", "no_changes")

            # Save current check time for next run
            _save_check_time(services, current_time)

            main_span.set_attribute("files_changed", len(changed_files))
            click.echo("Drive watcher completed successfully")

        except Exception as e:
            click.echo(f"Error in drive watcher: {e}", err=True)
            main_span.set_attribute("status", "error")
            main_span.set_attribute("error", str(e))
            raise
