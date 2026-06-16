"""
Google Drive watch management.

Provides functionality to initialize and renew Google Drive
changes.watch subscriptions and persist channel metadata and
page tokens to GCS.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import click
from cloudevents.http import CloudEvent
from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.auth import default
from google.cloud import storage
from googleapiclient.discovery import build

from ..common.config import get_settings
from ..common.tracing import get_tracer, setup_tracing
from ..worker.gcp import get_credentials

_CHANNEL_METADATA_PATH = "drivewatcher/channel_metadata.json"
_PAGE_TOKEN_PATH = "drivewatcher/page_token.json"
_ONE_DAY_MS = 24 * 60 * 60 * 1000


@lru_cache(maxsize=1)
def _get_services() -> dict:
    """Initialize services for the watch manager."""
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

    service_name = os.environ.get("K_SERVICE", "songbook-drivewatch")
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    drive_service = build("drive", "v3", credentials=creds)
    storage_client = storage.Client(project=project_id)

    return {
        "tracer": tracer,
        "drive": drive_service,
        "storage_client": storage_client,
        "project_id": project_id,
    }


def get_channel_metadata(services: dict) -> Optional[dict]:
    """Read stored channel metadata from GCS."""
    try:
        settings = get_settings()
        bucket_name = settings.caching.gcs.worker_cache_bucket
        bucket = services["storage_client"].bucket(bucket_name)
        blob = bucket.get_blob(_CHANNEL_METADATA_PATH)
        if not blob:
            return None
        return json.loads(blob.download_as_text())
    except (NotFound, json.JSONDecodeError, KeyError) as e:
        click.echo(f"Error reading channel metadata: {e}", err=True)
        return None


def save_channel_metadata(services: dict, metadata: dict) -> None:
    """Persist channel metadata to GCS."""
    settings = get_settings()
    bucket_name = settings.caching.gcs.worker_cache_bucket
    bucket = services["storage_client"].bucket(bucket_name)
    blob = bucket.blob(_CHANNEL_METADATA_PATH)
    blob.upload_from_string(
        json.dumps(metadata, indent=2),
        content_type="application/json",
    )


def get_page_token(services: dict) -> Optional[str]:
    """Read the stored changes.list page token from GCS."""
    try:
        settings = get_settings()
        bucket_name = settings.caching.gcs.worker_cache_bucket
        bucket = services["storage_client"].bucket(bucket_name)
        blob = bucket.get_blob(_PAGE_TOKEN_PATH)
        if not blob:
            return None
        data = json.loads(blob.download_as_text())
        return data.get("page_token")
    except (NotFound, json.JSONDecodeError, KeyError) as e:
        click.echo(f"Error reading page token: {e}", err=True)
        return None


def save_page_token(services: dict, page_token: str) -> None:
    """Persist the changes.list page token to GCS."""
    settings = get_settings()
    bucket_name = settings.caching.gcs.worker_cache_bucket
    bucket = services["storage_client"].bucket(bucket_name)
    blob = bucket.blob(_PAGE_TOKEN_PATH)
    blob.upload_from_string(
        json.dumps(
            {
                "page_token": page_token,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        content_type="application/json",
    )


def get_start_page_token(services: dict) -> str:
    """Fetch a fresh startPageToken from the Drive changes API."""
    response = (
        services["drive"].changes().getStartPageToken(supportsAllDrives=True).execute()
    )
    return response["startPageToken"]


def create_watch_channel(
    services: dict, page_token: str, webhook_url: str, verify_token: str
) -> dict:
    """
    Register a new changes.watch channel with the Drive API.

    Returns the channel metadata dict with channel_id, resource_id,
    and expiration.
    """
    channel_id = str(uuid.uuid4())
    expiration_ms = int(
        (datetime.now(timezone.utc) + timedelta(days=1)).timestamp() * 1000
    )

    body = {
        "id": channel_id,
        "type": "web_hook",
        "address": webhook_url,
        "token": verify_token,
        "expiration": expiration_ms,
    }

    response = (
        services["drive"]
        .changes()
        .watch(
            pageToken=page_token,
            body=body,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    return {
        "channel_id": response["id"],
        "resource_id": response["resourceId"],
        "expiration": response.get("expiration"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def stop_watch_channel(services: dict, channel_id: str, resource_id: str) -> None:
    """Stop an existing Drive watch channel."""
    try:
        services["drive"].channels().stop(
            body={"id": channel_id, "resourceId": resource_id}
        ).execute()
        click.echo(f"Stopped watch channel: {channel_id}")
    except NotFound:
        click.echo(
            f"Channel {channel_id} not found (may have already expired)",
            err=True,
        )
    except GoogleAPICallError as e:
        click.echo(
            f"Error stopping channel {channel_id}: {e}",
            err=True,
        )


def initialize_watch(services: dict, webhook_url: str, verify_token: str) -> dict:
    """
    Initialize a Drive changes.watch subscription for the first time.

    Gets a startPageToken, creates a watch channel pointing at the
    webhook URL, and persists channel_id, expiration, and the
    starting page token to GCS.
    """
    with services["tracer"].start_as_current_span("initialize_watch") as span:
        page_token = get_start_page_token(services)
        save_page_token(services, page_token)

        channel_metadata = create_watch_channel(
            services, page_token, webhook_url, verify_token
        )
        channel_metadata["page_token"] = page_token
        save_channel_metadata(services, channel_metadata)

        span.set_attribute("channel_id", channel_metadata["channel_id"])
        click.echo(f"Watch initialized: channel_id={channel_metadata['channel_id']}")
        return channel_metadata


def renew_watch(services: dict, webhook_url: str, verify_token: str) -> dict:
    """
    Rotate the Drive watch channel.

    Creates a new channel first (so we never have zero channels),
    persists its metadata, then stops the old channel.  Raises on
    channel-creation failure so Cloud Scheduler will retry.
    """
    with services["tracer"].start_as_current_span("renew_watch") as span:
        existing_metadata = get_channel_metadata(services)

        page_token = get_page_token(services)
        if not page_token:
            page_token = get_start_page_token(services)
            save_page_token(services, page_token)

        new_metadata = create_watch_channel(
            services, page_token, webhook_url, verify_token
        )
        new_metadata["page_token"] = page_token
        save_channel_metadata(services, new_metadata)

        span.set_attribute("new_channel_id", new_metadata["channel_id"])
        click.echo(f"New watch channel created: {new_metadata['channel_id']}")

        if existing_metadata:
            stop_watch_channel(
                services,
                existing_metadata["channel_id"],
                existing_metadata["resource_id"],
            )
            span.set_attribute("old_channel_id", existing_metadata["channel_id"])

        return new_metadata


def drivewatch_main(cloud_event: CloudEvent) -> None:
    """
    Cloud Function entry point for Drive watch initialization and renewal.

    Triggered by Cloud Scheduler every 23 hours. Creates a new watch
    channel (or initializes one on first run) and stops the previous
    channel to ensure exactly one active subscription at all times.
    """
    services = _get_services()

    with services["tracer"].start_as_current_span("drivewatch_main") as main_span:
        webhook_url = os.environ.get("DRIVE_WEBHOOK_URL", "")
        verify_token = os.environ.get("VERIFY_TOKEN", "")

        if not webhook_url:
            raise RuntimeError("DRIVE_WEBHOOK_URL environment variable is not set")
        if not verify_token:
            raise RuntimeError("VERIFY_TOKEN environment variable is not set")

        existing_metadata = get_channel_metadata(services)

        if existing_metadata:
            click.echo(f"Renewing watch channel: {existing_metadata['channel_id']}")
            result = renew_watch(services, webhook_url, verify_token)
            main_span.set_attribute("action", "renewed")
        else:
            click.echo("No existing channel; initializing new watch")
            result = initialize_watch(services, webhook_url, verify_token)
            main_span.set_attribute("action", "initialized")

        main_span.set_attribute("channel_id", result["channel_id"])
        click.echo("Drive watch management completed successfully")
