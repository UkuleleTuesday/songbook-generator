"""
Tag updater cloud function.

This module provides functionality to update Google Drive file tags
based on file change events published by the drivewatcher service.
"""

import base64
import json
import os
from functools import lru_cache
from typing import List

import click
from cloudevents.http import CloudEvent
from google.auth import default
from googleapiclient.discovery import build

from ..common.config import get_settings
from ..common.tracing import get_tracer, setup_tracing
from ..cache_updater.tags import Tagger
from ..worker.gcp import get_credentials
from ..worker.models import File


@lru_cache(maxsize=1)
def _get_services():
    """Initialize services for the tag updater."""
    settings = get_settings()
    setup_tracing("tagupdater")
    tracer = get_tracer(__name__)

    # Determine project ID from default credentials
    _, project_id = default()
    if project_id:
        os.environ["GCP_PROJECT_ID"] = project_id
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

    # Get credentials for tagging (needs drive write permissions)
    tagger_credential_config = settings.google_cloud.credentials.get(
        "songbook-cache-updater"
    )
    if not tagger_credential_config:
        raise click.Abort("Credential config 'songbook-cache-updater' not found.")

    tagger_creds = get_credentials(
        scopes=tagger_credential_config.scopes,
        target_principal=tagger_credential_config.principal,
    )

    # Create Google Drive service for tagging
    drive_service = build("drive", "v3", credentials=tagger_creds)

    return {
        "tracer": tracer,
        "drive": drive_service,
        "tagger": Tagger(drive_service),
    }


def _parse_cloud_event(cloud_event: CloudEvent) -> dict:
    """
    Parse a CloudEvent from the drivewatcher to extract changed files.

    Args:
        cloud_event: The incoming CloudEvent object from drivewatcher.

    Returns:
        A dictionary containing the parsed changed files list.
    """
    click.echo("--- Received CloudEvent ---")
    click.echo(f"CloudEvent object: {cloud_event}")
    click.echo(f"Attributes: {cloud_event.get_attributes()}")
    click.echo(f"Data: {cloud_event.get_data()}")
    click.echo("---------------------------")

    data = cloud_event.get_data() or {}

    # For Pub/Sub events, data is nested under 'message'
    if "message" in data:
        message_data = data["message"]["data"]
        # Decode base64 encoded message data
        decoded_data = base64.b64decode(message_data).decode("utf-8")
        message_content = json.loads(decoded_data)
    else:
        # Direct event data
        message_content = data

    changed_files = message_content.get("changed_files", [])

    return {
        "changed_files": changed_files,
        "check_time": message_content.get("check_time"),
        "file_count": message_content.get("file_count", len(changed_files)),
    }


def _convert_to_file_objects(changed_files: List[dict]) -> List[File]:
    """
    Convert changed file dicts from drivewatcher to File objects.

    Args:
        changed_files: List of file change dicts from drivewatcher.

    Returns:
        List of File objects suitable for tagging.
    """
    file_objects = []

    for file_data in changed_files:
        file_obj = File(
            id=file_data["id"],
            name=file_data["name"],
            properties=file_data.get("properties", {}),
            mimeType=file_data.get("mime_type"),
            parents=file_data.get("parents", []),
        )
        file_objects.append(file_obj)

    return file_objects


def tagupdater_main(cloud_event: CloudEvent):
    """
    Cloud Function entry point for updating Google Drive file tags.

    This function is triggered by file change events from the drivewatcher
    service and updates tags for individual files to avoid bulk operation
    timeouts.

    Args:
        cloud_event (CloudEvent): The CloudEvent from drivewatcher Pub/Sub topic.
    """
    services = _get_services()

    with services["tracer"].start_as_current_span("tagupdater_main") as main_span:
        try:
            # Parse the event to get changed files
            event_data = _parse_cloud_event(cloud_event)
            changed_files = event_data["changed_files"]

            if not changed_files:
                click.echo("No changed files to process")
                main_span.set_attribute("status", "no_files")
                return

            main_span.set_attribute("files_to_process", len(changed_files))
            main_span.set_attribute(
                "check_time", event_data.get("check_time", "unknown")
            )

            click.echo(f"Processing {len(changed_files)} changed files for tagging")

            # Convert to File objects for tagging
            file_objects = _convert_to_file_objects(changed_files)

            # Update tags for each file individually
            processed_count = 0
            error_count = 0

            for file_obj in file_objects:
                try:
                    with services["tracer"].start_as_current_span(
                        "update_file_tags",
                        attributes={"file.id": file_obj.id, "file.name": file_obj.name},
                    ):
                        click.echo(
                            f"Updating tags for {file_obj.name} (ID: {file_obj.id})"
                        )
                        services["tagger"].update_tags(file_obj)
                        processed_count += 1

                except (OSError, ValueError, RuntimeError) as e:
                    click.echo(
                        f"Error updating tags for {file_obj.name}: {e}", err=True
                    )
                    error_count += 1

            # Set final status
            main_span.set_attribute("files_processed", processed_count)
            main_span.set_attribute("files_error", error_count)

            if error_count == 0:
                main_span.set_attribute("status", "success")
                click.echo(f"Successfully updated tags for {processed_count} files")
            else:
                main_span.set_attribute("status", "partial_success")
                click.echo(
                    f"Updated tags for {processed_count} files, {error_count} errors"
                )

        except Exception as e:
            click.echo(f"Error in tag updater: {e}", err=True)
            main_span.set_attribute("status", "error")
            main_span.set_attribute("error", str(e))
            raise
