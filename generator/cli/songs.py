import json

import click

from ..common.config import get_settings
from ..common.filters import parse_filters
from ..common.gdrive import GoogleDriveClient
from ..worker.pdf import _make_song_source, collect_and_sort_files, init_services
from .utils import SubcmdGroup, _resolve_file_id, global_options


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
@click.option(
    "--modified-since",
    type=click.DateTime(
        formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]
    ),
    default=None,
    help=(
        "Only list songs modified in Drive since this UTC timestamp, e.g. "
        "--modified-since 2026-07-11 or --modified-since 2026-07-11T20:49:19. "
        "Can be used on its own or narrowed further with --edition/--filter."
    ),
)
def list_songs(
    ctx,
    source_folder: str,
    edition: str,
    filter_str: tuple,
    modified_since,
    **kwargs,
):
    """List songs matching a given filter expression or edition."""
    if not edition and not filter_str and not modified_since:
        raise click.UsageError(
            "Either --edition, --filter or --modified-since must be provided."
        )
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
    source_folders = list(source_folder) if source_folder else []

    if modified_since:
        click.echo(f"Fetching files modified since {modified_since}")

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
        client_filter = parse_filters(edition_config.sections.songs.filters)

    files = collect_and_sort_files(
        song_source=_make_song_source(drive, cache),
        source_folders=source_folders,
        client_filter=client_filter,
        modified_after=modified_since,
    )

    if not files:
        click.echo("No songs found matching the specified criteria.")
        return

    for file in files:
        click.echo(file.name)


@songs.command("search")
@click.argument("file_identifier")
def search_song(file_identifier):
    """Resolve a file ID or name and print its metadata as JSON."""
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
    file_id = _resolve_file_id(gdrive_client, file_identifier)
    files = gdrive_client.get_files_metadata_by_ids([file_id])
    if not files:
        click.echo(
            f"Error: Could not retrieve metadata for '{file_identifier}'.", err=True
        )
        raise click.Abort()

    f = files[0]
    click.echo(
        json.dumps(
            {
                "id": f.id,
                "name": f.name,
                "mimeType": f.mimeType,
                "parents": f.parents,
                "properties": f.properties,
            }
        )
    )
