import json
import sys

import click
from google import genai
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..common.caching import init_cache
from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..common.metadata_store import get_metadata_store
from ..tagupdater.tags import Tagger
from ..worker.gcp import get_credentials
from ..worker.pdf import init_services
from .utils import SubcmdGroup, _resolve_file_id


@click.group(cls=SubcmdGroup)
def tags():
    """Get and set tags (custom properties) on Google Drive files."""


@tags.command(name="get")
@click.argument("file_identifier")
@click.argument("key", required=False)
def get_tag(file_identifier, key):
    """Get a specific tag or all tags for a Google Drive file."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)

    if settings.metadata_store.firestore_read_enabled:
        store = get_metadata_store()
        properties = store.get_properties(file_id)
        if properties is None:
            click.echo("No Firestore doc found, falling back to Drive.", err=True)
            properties = gdrive_client.get_file_properties(file_id)
    else:
        properties = gdrive_client.get_file_properties(file_id)

    if properties is None:
        raise click.Abort()

    if key:
        if key in properties:
            click.echo(properties[key])
        else:
            click.echo(f"Error: Tag '{key}' not found.", err=True)
            raise click.Abort()
    else:
        click.echo(json.dumps(properties, indent=2))


@tags.command(name="set")
@click.argument("file_identifier")
@click.argument("key")
@click.argument("value")
def set_tag(file_identifier, key, value):
    """Set a tag on a Google Drive file."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)

    if settings.metadata_store.drive_write_enabled:
        if gdrive_client.set_file_property(file_id, key, value):
            click.echo(f"Successfully set tag '{key}' to '{value}' in Drive.")
        else:
            click.echo("Failed to set tag in Drive.", err=True)
            raise click.Abort()

    if settings.metadata_store.firestore_write_enabled:
        store = get_metadata_store()
        props = store.get_properties(file_id) or {}
        props[key] = value
        store.write(file_id, props)
        click.echo(f"Successfully set tag '{key}' to '{value}' in Firestore.")


@tags.command(name="delete")
@click.argument("file_identifier")
@click.argument("key")
def delete_tag(file_identifier, key):
    """Delete a tag from a Google Drive file."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)

    if settings.metadata_store.drive_write_enabled:
        try:
            file_metadata = (
                gdrive_client.drive.files()
                .get(fileId=file_id, fields="properties")
                .execute()
            )
            properties = file_metadata.get("properties", {})

            if key not in properties:
                click.echo(f"Tag '{key}' not found on file in Drive. No changes made.")
            else:
                gdrive_client.drive.files().update(
                    fileId=file_id,
                    body={"properties": {key: None}},
                    fields="properties",
                ).execute()
                click.echo(f"Successfully deleted tag '{key}' from Drive.")
        except HttpError as e:
            click.echo(f"Failed to delete tag '{key}' from Drive: {e}", err=True)
            raise click.Abort()

    if settings.metadata_store.firestore_write_enabled:
        store = get_metadata_store()
        props = store.get_properties(file_id)
        if props is None:
            click.echo("No Firestore doc found. No changes made.")
        elif key not in props:
            click.echo(f"Tag '{key}' not found in Firestore. No changes made.")
        else:
            store.delete_property(file_id, key)
            click.echo(f"Successfully deleted tag '{key}' from Firestore.")


@tags.command(name="update")
@click.argument("file_identifier", required=False)
@click.option(
    "--all",
    is_flag=True,
    default=False,
    help="Run the auto-tagger on all song sheets.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what tags would be applied without making any changes.",
)
@click.option(
    "--trigger-field",
    default=None,
    help=(
        "Only write metadata if this field's value changes. "
        "Overrides the config/env setting."
    ),
)
@click.option(
    "--with-llm-tags/--without-llm-tags",
    default=None,
    help=(
        "Enable or disable LLM-backed tag enrichment (year, duration, genre). "
        "Overrides the TAGUPDATER_LLM_TAGGING_ENABLED config/env setting (on by default)."
    ),
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Print computed tag values for each file.",
)
def update_tags(file_identifier, all, dry_run, trigger_field, with_llm_tags, verbose):
    """Run the auto-tagger on a specific Google Drive file or all files."""
    if not file_identifier and not all:
        click.echo(
            "Error: Either a file identifier or the --all flag must be provided.",
            err=True,
        )
        raise click.Abort()
    if file_identifier and all:
        click.echo(
            "Error: Cannot use both a file identifier and the --all flag.", err=True
        )
        raise click.Abort()

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("tag-updater")
    if not credential_config:
        click.echo("Error: credential config 'tag-updater' not found.", err=True)
        raise click.Abort()

    creds = get_credentials(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    cache = init_cache()
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive_service)

    if file_identifier:
        file_id = _resolve_file_id(gdrive_client, file_identifier)
        files_to_process = gdrive_client.get_files_metadata_by_ids([file_id])
        if not files_to_process:
            click.echo(
                f"Error: Could not retrieve metadata for file ID {file_id}", err=True
            )
            raise click.Abort()
    else:  # --all flag
        click.echo("Fetching all song sheets from Drive...")
        files_to_process = gdrive_client.query_drive_files(
            settings.song_sheets.folder_ids
        )

    effective_trigger_field = (
        trigger_field
        if trigger_field is not None
        else settings.tag_updater.trigger_field
    )
    effective_llm_tagging = (
        with_llm_tags
        if with_llm_tags is not None
        else settings.tag_updater.llm_tagging_enabled
    )
    if effective_llm_tagging:
        genai_client = genai.Client(
            vertexai=True,
            project=settings.google_cloud.project_id,
            location=settings.caching.gcs.region or "us-central1",
        )
    else:
        genai_client = None
        click.echo("LLM tagging disabled (use --with-llm-tags to enable).")
    metadata_store = (
        get_metadata_store()
        if settings.metadata_store.firestore_write_enabled
        else None
    )
    if metadata_store is not None:
        click.echo(
            "Firestore metadata write enabled (collection "
            f"'{settings.metadata_store.firestore_collection}')."
        )
    if not settings.metadata_store.drive_write_enabled:
        click.echo("Drive metadata write disabled.")
    tagger = Tagger(
        drive_service=drive_service,
        docs_service=docs_service,
        trigger_field=effective_trigger_field,
        genai_client=genai_client,
        llm_tagging_enabled=effective_llm_tagging,
        metadata_store=metadata_store,
        drive_write_enabled=settings.metadata_store.drive_write_enabled,
    )
    failed_updates = {}

    for file_obj in files_to_process:
        try:
            if file_obj.mimeType != "application/vnd.google-apps.document":
                click.echo(
                    f"Skipping '{file_obj.name}' (not a Google Doc).",
                )
                continue

            click.echo(f"Running auto-tagger for '{file_obj.name}'...")
            if dry_run:
                click.echo("  (Dry run mode)")

            tagger.update_tags(file_obj, dry_run=dry_run, verbose=verbose)
        except HttpError as e:
            error_message = f"Failed to update tags for '{file_obj.name}': {e}"
            click.echo(f"ERROR: {error_message}", err=True)
            failed_updates[file_obj.name] = str(e)
        except Exception as e:  # noqa: BLE001 - Catch all for CLI error reporting
            error_message = f"An unexpected error occurred for '{file_obj.name}': {e}"
            click.echo(f"ERROR: {error_message}", err=True)
            failed_updates[file_obj.name] = str(e)

    if failed_updates:
        click.echo("\n--- Auto-tagger summary ---", err=True)
        click.echo("Auto-tagger run completed with some failures.", err=True)
        click.echo("Failed files:", err=True)
        for file_name, error in failed_updates.items():
            click.echo(f"  - {file_name}: {error}", err=True)
        sys.exit(1)

    click.echo("Auto-tagger run complete.")
