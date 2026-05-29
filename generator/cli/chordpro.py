from pathlib import Path

import click
from googleapiclient.discovery import build

from ..common.caching import init_cache
from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..worker.chordpro import generate_song_chordpro
from ..worker.gcp import get_credentials
from .utils import _resolve_file_id, global_options


def _slugify(name: str) -> str:
    """Convert a file name like 'Love Me Do' to 'Love_Me_Do.cho'."""
    return name + ".cho"


@click.command("generate-chordpro")
@global_options
@click.pass_context
@click.argument("song_identifier")
@click.option(
    "--destination-path",
    "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Where to save the generated ChordPro file (default: out/<song-name>.cho)",
)
@click.option(
    "--no-annotations",
    is_flag=True,
    help="Strip all annotations (stage directions, performer markers)",
)
@click.option(
    "--detect-sections",
    is_flag=True,
    help="Attempt to auto-detect verse/chorus/bridge sections",
)
def generate_chordpro(
    ctx,
    song_identifier: str,
    destination_path: Path | None,
    no_annotations: bool,
    detect_sections: bool,
    **kwargs,
):
    """Generate a ChordPro file for a song from its Google Drive document."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo("Error: credential config 'songbook-generator' not found.", err=True)
        raise click.Abort()

    creds = get_credentials(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    cache = init_cache()
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive_service)

    file_id = _resolve_file_id(gdrive_client, song_identifier)

    files_meta = gdrive_client.get_files_metadata_by_ids([file_id])
    if not files_meta:
        click.echo(f"Error: could not fetch metadata for file ID {file_id}.", err=True)
        raise click.Abort()
    file_name = files_meta[0].name

    if destination_path is None:
        destination_path = Path("out") / _slugify(file_name)

    click.echo(f"Generating ChordPro for: {file_name}")
    generate_song_chordpro(
        docs_service,
        file_id,
        file_name,
        destination_path,
        include_annotations=not no_annotations,
        detect_sections=detect_sections,
    )
    click.echo(f"Saved to: {destination_path}")
