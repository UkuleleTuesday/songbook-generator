from pathlib import Path

import click
from googleapiclient.errors import HttpError

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..worker.pdf import init_services
from ..worker.pptx import generate_song_pptx
from .utils import _resolve_file_id, global_options


@click.command("generate-pptx")
@global_options
@click.pass_context
@click.argument("song_identifier")
@click.option(
    "--destination-path",
    "-d",
    type=click.Path(path_type=Path),
    default="out/song.pptx",
    help="Where to save the generated PPTX file.",
    show_default=True,
)
def generate_pptx(ctx, song_identifier: str, destination_path: Path, **kwargs):
    """Generate a PPTX presentation for a song.

    SONG_IDENTIFIER may be a Google Drive file ID or a song name (or partial
    name – the closest match will be used, like other song commands).
    """
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

    file_id = _resolve_file_id(gdrive_client, song_identifier)

    files = gdrive_client.get_files_metadata_by_ids([file_id])
    if not files:
        click.echo(
            f"Error: Could not retrieve metadata for '{song_identifier}'.", err=True
        )
        raise click.Abort()

    song_file = files[0]
    click.echo(f"Fetching content for: {song_file.name} (ID: {song_file.id})")

    try:
        text = gdrive_client.export_as_plain_text(song_file)
    except HttpError as e:
        click.echo(f"Error: Could not export document as plain text: {e}", err=True)
        raise click.Abort()

    click.echo(f"Generating PPTX: {destination_path}")
    generate_song_pptx(
        song_name=song_file.name,
        text=text,
        output_path=destination_path,
    )
    click.echo(f"✅ PPTX saved to: {destination_path}")
