import traceback
import os
import click
from pathlib import Path


from .common.config import get_settings
from .merger.main import fetch_and_merge_pdfs
import json
from .common.gdrive import get_file_properties, set_file_property, search_files_by_name
from .merger.sync import download_gcs_cache_to_local, sync_cache
from .worker.filters import FilterParser
from .worker.pdf import generate_songbook, init_services


def make_cli_progress_callback():
    """Return a callback that displays progress updates to the console."""

    def _callback(percent: float, message: str = None):
        percentage = int(percent * 100)
        click.echo(f"[{percentage:3d}%] {message or ''}")

    return _callback


@click.group()
@click.pass_context
def cli(ctx):
    """Songbook Generator CLI tool."""
    ctx.ensure_object(dict)


@cli.command()
@click.pass_context
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=lambda: get_settings().song_sheets.folder_ids,
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option(
    "--destination-path",
    "-d",
    type=click.Path(path_type=Path),
    default="out/songbook.pdf",
    help="Where to save the generated pdf",
)
@click.option(
    "--open-generated-pdf",
    is_flag=True,
    help="Open the generated pdf",
)
@click.option(
    "--cover-file-id",
    "-c",
    default=lambda: get_settings().cover.file_id,
    help="File ID of the cover",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=None,
    help="Limit the number of files to process (no limit by default)",
)
@click.option(
    "--filter",
    "-f",
    help="Filter files using property syntax. Examples: 'specialbooks:contains:regular', 'year:gte:2000', 'artist:equals:Beatles', 'difficulty:in:easy,medium'",
)
@click.option(
    "--preface-file-id",
    multiple=True,
    help="Google Drive file IDs for preface pages (after cover, before TOC). Can be specified multiple times.",
)
@click.option(
    "--postface-file-id",
    multiple=True,
    help="Google Drive file IDs for postface pages (at the very end). Can be specified multiple times.",
)
def generate(
    ctx,
    source_folder: str,
    destination_path: Path,
    open_generated_pdf,
    cover_file_id: str,
    limit: int,
    filter,
    preface_file_id,
    postface_file_id,
):
    """Generates a songbook PDF from Google Drive files."""

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo("Error: credential config 'songbook-generator' not found.", err=True)
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )

    client_filter = None
    if filter:
        try:
            client_filter = FilterParser.parse_simple_filter(filter)
            click.echo(f"Applying client-side filter: {filter}")
        except ValueError as e:
            click.echo(f"Error parsing filter: {e}")
            return

    # Convert tuples to lists
    source_folders = list(source_folder) if source_folder else []
    preface_file_ids = list(preface_file_id) if preface_file_id else None
    postface_file_ids = list(postface_file_id) if postface_file_id else None

    if preface_file_ids:
        click.echo(f"Using {len(preface_file_ids)} preface file(s)")
    if postface_file_ids:
        click.echo(f"Using {len(postface_file_ids)} postface file(s)")

    progress_callback = make_cli_progress_callback()
    generate_songbook(
        drive,
        cache,
        source_folders,
        destination_path,
        limit,
        cover_file_id,
        client_filter,
        preface_file_ids,
        postface_file_ids,
        on_progress=progress_callback,
    )
    if open_generated_pdf:
        click.echo(f"Opening generated songbook: {destination_path}")
        click.launch(str(destination_path))


@cli.command(name="sync-cache")
@click.pass_context
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=lambda: get_settings().song_sheets.folder_ids,
    help="Drive folder IDs to sync from (can be passed multiple times)",
)
@click.option(
    "--no-metadata",
    is_flag=True,
    default=False,
    help="Disable syncing of file metadata from Drive to GCS.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force a full sync, ignoring modification times.",
)
@click.option(
    "--update-tags-only",
    is_flag=True,
    default=False,
    help="Only update tags on Drive files, do not sync to GCS cache.",
)
@click.option(
    "--update-tags",
    is_flag=True,
    default=False,
    help="Update tags on Drive files in addition to syncing to GCS cache.",
)
def sync_cache_command(
    source_folder, no_metadata, force, update_tags_only, update_tags
):
    """Syncs files and metadata from Google Drive to the GCS cache."""
    try:
        click.echo("Starting cache synchronization (CLI mode)")
        from .merger import main as merger_main

        services = merger_main._get_services()
        source_folders = list(source_folder) if source_folder else []

        if not source_folders:
            click.echo("No source folders provided. Nothing to sync.", err=True)
            raise click.Abort()

        last_merge_time = None
        if not force:
            last_merge_time = merger_main._get_last_merge_time(services["cache_bucket"])
        else:
            click.echo("Force flag set. Performing a full sync.")

        click.echo(f"Syncing folders: {source_folders}")
        sync_cache(
            source_folders,
            services,
            with_metadata=not no_metadata,
            modified_after=last_merge_time,
            update_tags_only=update_tags_only,
            update_tags=update_tags,
        )
        click.echo("Cache synchronization complete.")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Cache sync operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cli.command(name="download-cache")
@click.option(
    "--with-metadata",
    is_flag=True,
    default=False,
    help="Also download GCS object metadata and save it to a .metadata.json file.",
)
def download_cache_command(with_metadata):
    """Downloads the GCS cache to the local cache directory."""
    try:
        click.echo("Starting GCS cache download (CLI mode)")
        from .merger import main as merger_main

        services = merger_main._get_services()
        local_cache_dir = get_settings().caching.local.dir
        click.echo(f"Local cache directory: {local_cache_dir}")

        download_gcs_cache_to_local(
            services, os.path.expanduser(local_cache_dir), with_metadata
        )

        click.echo("GCS cache download complete.")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Cache download operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cli.command(name="merge-pdfs")
@click.option(
    "--output",
    "-o",
    default="merged-songbook.pdf",
    help="Output file path for merged PDF (default: merged-songbook.pdf)",
)
def merge_pdfs(output: str):
    """CLI interface for merging PDFs from GCS cache."""
    try:
        click.echo("Starting PDF merge operation (CLI mode)")

        # Lazily import to avoid issues if merger dependencies are not available
        from .merger import main as merger_main

        # Manually get the services since we are not in a Cloud Function
        services = merger_main._get_services()
        click.echo("Merging PDFs from all song sheets in cache.")
        result_path = fetch_and_merge_pdfs(output, services)

        if not result_path:
            click.echo("Error: No PDF files found to merge", err=True)
            raise click.Abort()

        click.echo(f"Successfully created merged PDF: {result_path}")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Merge operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cli.command(name="print-settings")
def print_settings():
    """Prints the current settings for debugging purposes."""
    click.echo("Current application settings:")
    settings = get_settings()
    click.echo(settings.model_dump_json(indent=2))


@cli.group()
def tags():
    """Get and set tags (custom properties) on Google Drive files."""


def _resolve_file_id(drive, file_identifier: str) -> str:
    """
    Resolve a file identifier to a Google Drive file ID.
    If it's not a valid ID, search by name.
    """
    # Simple check if it looks like a Google Drive file ID
    if len(file_identifier) > 20 and " " not in file_identifier:
        return file_identifier  # Assume it's an ID

    # Otherwise, search by name
    settings = get_settings()
    source_folders = settings.song_sheets.folder_ids
    found_files = search_files_by_name(drive, file_identifier, source_folders)

    if not found_files:
        click.echo(f"Error: No file found matching '{file_identifier}'.", err=True)
        raise click.Abort()

    if len(found_files) > 1:
        click.echo(
            f"Error: Found multiple files matching '{file_identifier}'. Please be more specific or use a file ID.",
            err=True,
        )
        for f in found_files:
            click.echo(f"  - {f.name} (ID: {f.id})", err=True)
        raise click.Abort()

    file_id = found_files[0].id
    click.echo(f"Found file: {found_files[0].name} (ID: {file_id})")
    return file_id


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

    drive, _ = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    file_id = _resolve_file_id(drive, file_identifier)
    properties = get_file_properties(drive, file_id)

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

    drive, _ = init_services(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    file_id = _resolve_file_id(drive, file_identifier)
    if set_file_property(drive, file_id, key, value):
        click.echo(f"Successfully set tag '{key}' to '{value}'.")
    else:
        click.echo("Failed to set tag.", err=True)
        raise click.Abort()


if __name__ == "__main__":
    cli()
