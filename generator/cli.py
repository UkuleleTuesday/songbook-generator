import traceback
import click
from pathlib import Path


from .common.config import load_config_folder_ids, load_cover_config
from .merger.main import fetch_and_merge_pdfs
from .merger.sync import sync_cache
from .worker.filters import FilterParser
from .worker.pdf import generate_songbook, init_services


def make_cli_progress_callback():
    """Return a callback that displays progress updates to the console."""

    def _callback(percent: float, message: str = None):
        percentage = int(percent * 100)
        click.echo(f"[{percentage:3d}%] {message or ''}")

    return _callback


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=load_config_folder_ids(),
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option(
    "--destination-path",
    "-d",
    required=True,
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
    default=load_cover_config(),
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
@click.option(
    "--service-account-key",
    envvar="GOOGLE_APPLICATION_CREDENTIALS",
    type=click.Path(exists=True),
    help="Path to a service account key file for authentication. "
    "Can also be set via GOOGLE_APPLICATION_CREDENTIALS env var.",
)
def generate(
    source_folder: str,
    destination_path: Path,
    open_generated_pdf,
    cover_file_id: str,
    limit: int,
    filter,
    preface_file_id,
    postface_file_id,
    service_account_key: str,
):
    """Generates a songbook PDF from Google Drive files."""
    drive, cache = init_services(service_account_key)

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
        click.launch(destination_path)


@cli.command(name="sync-cache")
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=load_config_folder_ids(),
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
def sync_cache_command(source_folder, no_metadata, force):
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
        )
        click.echo("Cache synchronization complete.")

    except Exception as e:
        click.echo(f"Cache sync operation failed: {str(e)}", err=True)
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

    except Exception as e:
        click.echo(f"Merge operation failed: {str(e)}", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


if __name__ == "__main__":
    cli()
