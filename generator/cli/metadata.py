"""CLI commands for the Firestore-backed song metadata store."""

import json

import click

from ..common.metadata_store import get_metadata_store
from .utils import SubcmdGroup


@click.group(cls=SubcmdGroup)
def metadata():
    """Manage the Firestore-backed song metadata store."""


@metadata.command(name="copy")
@click.option(
    "--source-database",
    default=None,
    help=(
        "Source Firestore database to read from. Defaults to the configured "
        "database (the production default database when FIRESTORE_DATABASE is "
        "unset)."
    ),
)
@click.option(
    "--dest-database",
    required=True,
    help="Destination Firestore database to write into (e.g. 'pr-421').",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Read and count source documents without writing to the destination.",
)
def copy(source_database, dest_database, dry_run):
    """Copy all metadata documents from one Firestore database to another.

    Reads every document from the source database's metadata collection and
    writes it into the destination database (merge semantics). Used to backfill
    an isolated per-PR preview database from production so previews see the same
    song properties as main.
    """
    if source_database == dest_database:
        raise click.ClickException(
            f"Source and destination databases are identical "
            f"('{dest_database}'); refusing to copy."
        )

    source_store = get_metadata_store(database=source_database)
    all_docs = source_store.get_all()
    click.echo(
        f"Read {len(all_docs)} documents from source database "
        f"'{source_database or '(default)'}'."
    )

    if dry_run:
        click.echo(
            f"DRY RUN: would write {len(all_docs)} documents to '{dest_database}'."
        )
        return

    dest_store = get_metadata_store(database=dest_database)
    items = (
        (file_id, doc.get("properties", {}), doc.get("gdrive_file_name"))
        for file_id, doc in all_docs.items()
    )
    written = dest_store.bulk_write(items)
    click.echo(
        f"Copied {written} documents to database '{dest_database}' "
        f"collection '{dest_store.collection}'."
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
