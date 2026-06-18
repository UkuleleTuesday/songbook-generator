"""CLI commands for the Firestore-backed song metadata store (issue #281)."""

import json

import click

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..common.metadata_store import get_metadata_store
from ..worker.pdf import init_services
from .utils import SubcmdGroup


@click.group(cls=SubcmdGroup)
def metadata():
    """Manage the Firestore-backed song metadata store (#281)."""


def _init_drive_client() -> GoogleDriveClient:
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-cache-updater")
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-cache-updater' not found.", err=True
        )
        raise click.Abort()
    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    return GoogleDriveClient(cache=cache, drive=drive)


@metadata.command(name="backfill")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List what would be written without writing to Firestore.",
)
def backfill(dry_run):
    """Hydrate the Firestore metadata collection from Drive file properties.

    Reads every song sheet's custom properties from Google Drive and mirrors
    them into the Firestore metadata collection, one document per file (keyed by
    Drive file ID). Safe to re-run: writes use merge semantics.
    """
    settings = get_settings()
    gdrive_client = _init_drive_client()

    click.echo("Fetching all song sheets from Drive...")
    files = gdrive_client.query_drive_files(settings.song_sheets.folder_ids)
    click.echo(f"Found {len(files)} song sheets in Drive.")

    if dry_run:
        for f in files:
            click.echo(
                f"  would write {f.id} ({f.name}) -> {len(f.properties)} properties"
            )
        click.echo(f"DRY RUN: {len(files)} documents not written.")
        return

    store = get_metadata_store()
    written = store.bulk_write((f.id, f.properties, f.name) for f in files)
    click.echo(
        f"Wrote {written} documents to Firestore collection '{store.collection}'."
    )


@metadata.command(name="get")
@click.argument("file_id")
def get(file_id):
    """Fetch a single song's metadata document from Firestore by file ID."""
    store = get_metadata_store()
    doc = store.get(file_id)
    if doc is None:
        click.echo(f"No metadata document found for file ID '{file_id}'.", err=True)
        raise click.Abort()
    click.echo(json.dumps(doc, indent=2, default=str))
