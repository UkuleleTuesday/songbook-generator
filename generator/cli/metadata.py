"""CLI commands for the Firestore-backed song metadata store (issue #281)."""

import json

import click

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..common.metadata_store import get_metadata_store
from ..worker.pdf import init_services
from .utils import SubcmdGroup, _resolve_file_id


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

    A database-to-database copy is required rather than re-hydrating from Drive:
    Drive writes are disabled (#281), so some tags live only in Firestore and a
    Drive re-hydrate would miss them.
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


@metadata.command(name="diff")
@click.argument("file_identifier", required=False)
def diff(file_identifier):
    """Compare Firestore metadata against live Drive properties.

    With no argument: checks every song sheet in Drive against Firestore,
    reporting missing docs, extra docs, and per-key value mismatches.

    With FILE_IDENTIFIER: checks a single song by Drive file ID or name.

    Exits with a non-zero status code if any drift is found.
    """
    import sys

    settings = get_settings()
    gdrive_client = _init_drive_client()
    store = get_metadata_store()

    if file_identifier:
        file_id = _resolve_file_id(gdrive_client, file_identifier)
        drive_props = gdrive_client.get_file_properties(file_id) or {}
        firestore_props = store.get_properties(file_id)

        if firestore_props is None:
            click.echo(f"MISSING from Firestore: {file_id}")
            sys.exit(1)

        mismatches = _diff_properties(drive_props, firestore_props)
        if mismatches:
            click.echo(f"DRIFTED: {file_id}")
            for line in mismatches:
                click.echo(f"  {line}")
            sys.exit(1)
        else:
            click.echo(f"OK: {file_id} is in sync.")
        return

    click.echo("Fetching all song sheets from Drive...")
    drive_files = gdrive_client.query_drive_files(settings.song_sheets.folder_ids)
    drive_by_id = {f.id: f for f in drive_files}
    click.echo(f"Found {len(drive_files)} files in Drive.")

    click.echo("Fetching all Firestore metadata docs...")
    firestore_all = store.get_all()
    click.echo(f"Found {len(firestore_all)} docs in Firestore.")

    missing = [f for f in drive_files if f.id not in firestore_all]
    extra = [fid for fid in firestore_all if fid not in drive_by_id]
    drifted_files = []
    for f in drive_files:
        if f.id not in firestore_all:
            continue
        fs_props = firestore_all[f.id].get("properties", {})
        mismatches = _diff_properties(f.properties, fs_props)
        if mismatches:
            drifted_files.append((f, mismatches))

    if missing:
        click.echo(f"\nMISSING from Firestore ({len(missing)}):")
        for f in missing:
            click.echo(f"  {f.id}  {f.name}")

    if extra:
        click.echo(f"\nEXTRA in Firestore ({len(extra)}) (no matching Drive file):")
        for fid in extra:
            name = firestore_all[fid].get("gdrive_file_name", "")
            click.echo(f"  {fid}  {name}")

    if drifted_files:
        click.echo(f"\nDRIFTED ({len(drifted_files)}):")
        for f, mismatches in drifted_files:
            click.echo(f"  {f.id}  {f.name}")
            for line in mismatches:
                click.echo(f"    {line}")

    in_sync = len(drive_files) - len(missing) - len(drifted_files)
    click.echo(
        f"\nSummary: {in_sync} in sync, {len(missing)} missing, "
        f"{len(extra)} extra, {len(drifted_files)} drifted."
    )

    if missing or extra or drifted_files:
        sys.exit(1)


def _diff_properties(drive_props: dict, firestore_props: dict) -> list[str]:
    """Return a list of human-readable mismatch lines, empty if in sync."""
    lines = []
    all_keys = set(drive_props) | set(firestore_props)
    for key in sorted(all_keys):
        drive_val = drive_props.get(key)
        fs_val = firestore_props.get(key)
        if drive_val != fs_val:
            lines.append(f"{key}: Drive={drive_val!r}  Firestore={fs_val!r}")
    return lines
