from pathlib import Path

import click

from ..common.config import get_settings
from ..common.filters import FilterParser
from ..common.gdrive import GoogleDriveClient
from ..worker.pdf import (
    generate_songbook,
    generate_songbook_from_edition,
    init_services,
    load_edition_from_drive_folder,
)
from .utils import global_options, make_cli_progress_callback


@click.command()
@global_options
@click.pass_context
@click.option(
    "--edition",
    "-e",
    help=(
        "Songbook edition to generate. Accepts either a configured edition ID "
        "(from songbooks.yaml) or a Google Drive folder ID containing a "
        ".songbook.yaml config file."
    ),
)
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
    edition: str,
    source_folder: str,
    destination_path: Path,
    open_generated_pdf,
    cover_file_id: str,
    limit: int,
    filter,
    preface_file_id,
    postface_file_id,
    **kwargs,
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

    # Convert tuples to lists early
    source_folders = list(source_folder) if source_folder else []
    preface_file_ids = list(preface_file_id) if preface_file_id else None
    postface_file_ids = list(postface_file_id) if postface_file_id else None

    progress_callback = make_cli_progress_callback()

    if edition:
        # When using an edition, certain CLI flags are disallowed.
        conflicting_flags = {
            "--filter": filter,
            "--cover-file-id": cover_file_id != get_settings().cover.file_id,
            "--preface-file-id": preface_file_ids,
            "--postface-file-id": postface_file_ids,
        }
        used_conflicting = [
            flag for flag, present in conflicting_flags.items() if present
        ]
        if used_conflicting:
            click.echo(
                f"Error: Cannot use {', '.join(used_conflicting)} with --edition.",
                err=True,
            )
            raise click.Abort()

        # Try configured editions first, fall back to treating the value as a
        # Drive folder ID containing a .songbook.yaml.
        selected_edition = next((e for e in settings.editions if e.id == edition), None)
        songs_files = None
        if not selected_edition:
            click.echo(
                f"Edition '{edition}' not found in configuration, "
                "trying as Drive folder ID..."
            )
            gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
            try:
                selected_edition, songs_files = load_edition_from_drive_folder(
                    gdrive_client, edition
                )
            except ValueError as e:
                click.echo(f"Error: {e}", err=True)
                raise click.Abort()

        click.echo(
            f"Generating songbook for edition: {selected_edition.id} - {selected_edition.description}"
        )
        generate_songbook_from_edition(
            drive=drive,
            cache=cache,
            source_folders=source_folders,
            destination_path=destination_path,
            edition=selected_edition,
            limit=limit,
            on_progress=progress_callback,
            files=songs_files,
        )
    else:
        # Legacy mode without edition
        client_filter = None
        if filter:
            try:
                client_filter = FilterParser.parse_simple_filter(filter)
                click.echo(f"Applying client-side filter: {filter}")
            except ValueError as e:
                click.echo(f"Error parsing filter: {e}")
                return

        if preface_file_ids:
            click.echo(f"Using {len(preface_file_ids)} preface file(s)")
        if postface_file_ids:
            click.echo(f"Using {len(postface_file_ids)} postface file(s)")

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
