import click

from ..common.config import get_settings
from ..common.filters import parse_filters
from ..common.gdrive import GoogleDriveClient
from ..worker.pdf import collect_and_sort_files, init_services
from .utils import SubcmdGroup, global_options


@click.group(cls=SubcmdGroup)
def songs():
    """Browse and filter the song catalogue."""


@songs.command("list")
@global_options
@click.pass_context
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=lambda: get_settings().song_sheets.folder_ids,
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option("--edition", "-e", help="List songs from a predefined edition.")
@click.option(
    "--filter",
    "-f",
    "filter_str",
    multiple=True,
    help="Filter files using property syntax (can be passed multiple times for AND logic).",
)
def list_songs(ctx, source_folder: str, edition: str, filter_str: tuple, **kwargs):
    """List songs matching a given filter expression or edition."""
    if not edition and not filter_str:
        raise click.UsageError("Either --edition or --filter must be provided.")
    if edition and filter_str:
        raise click.UsageError("Cannot use --edition and --filter simultaneously.")

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo("Error: credential config 'songbook-generator' not found.", err=True)
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

    source_folders = list(source_folder) if source_folder else []

    client_filter = None
    if filter_str:
        filter_list = list(filter_str)
        click.echo(f"Fetching files matching filter: {filter_list}")
        client_filter = parse_filters(filter_list)
    elif edition:
        click.echo(f"Fetching files for edition: '{edition}'")
        edition_config = next((e for e in settings.editions if e.id == edition), None)
        if not edition_config:
            raise click.BadParameter(f"Edition '{edition}' not found in configuration.")
        client_filter = parse_filters(edition_config.filters)

    files = collect_and_sort_files(
        gdrive_client=gdrive_client,
        source_folders=source_folders,
        client_filter=client_filter,
    )

    if not files:
        click.echo("No songs found matching the specified criteria.")
        return

    for file in files:
        click.echo(file.name)
