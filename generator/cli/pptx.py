from importlib.resources import files
from pathlib import Path

import click

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..worker.pdf import init_services
from ..worker.pptx import generate_song_pptx
from .utils import _resolve_file_id, global_options

_DEFAULT_TEMPLATE = files("generator.templates").joinpath("song_slide_template.pptx")


def _default_template_path() -> Path:
    return Path(str(_DEFAULT_TEMPLATE))


def _slugify(name: str) -> str:
    """Convert a file name like 'Love Me Do - The Beatles' to 'Love_Me_Do.pptx'."""
    return name + ".pptx"


@click.command("generate-pptx")
@global_options
@click.pass_context
@click.argument("song_identifier")
@click.option(
    "--destination-path",
    "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Where to save the generated PPTX (default: out/<song-name>.pptx)",
)
@click.option(
    "--template",
    "-t",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Template PPTX to use (default: bundled song_slide_template.pptx)",
)
@click.option(
    "--annotations/--no-annotations",
    default=False,
    help="Include [stage direction] markers (default: exclude)",
)
@click.option(
    "--open-generated-pptx",
    is_flag=True,
    help="Open the generated PPTX after creation",
)
def generate_pptx(
    ctx,
    song_identifier: str,
    destination_path: Path | None,
    template: Path | None,
    annotations: bool,
    open_generated_pptx: bool,
    **kwargs,
):
    """Generate a projection PPTX for a song from its Google Drive document."""
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

    files_meta = gdrive_client.get_files_metadata_by_ids([file_id])
    if not files_meta:
        click.echo(f"Error: could not fetch metadata for file ID {file_id}.", err=True)
        raise click.Abort()
    file_name = files_meta[0].name

    if destination_path is None:
        destination_path = Path("out") / _slugify(file_name)

    template_path = template if template is not None else _default_template_path()

    click.echo(f"Generating PPTX for: {file_name}")
    generate_song_pptx(
        gdrive_client,
        file_id,
        file_name,
        template_path,
        destination_path,
        include_annotations=annotations,
    )
    click.echo(f"Saved to: {destination_path}")

    if open_generated_pptx:
        click.launch(str(destination_path))
