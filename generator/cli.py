import click

from pathlib import Path

from config import load_config_folder_ids, load_cover_config
from pdf import generate_songbook


def make_cli_progress_callback():
    """Return a callback that displays progress updates to the console."""

    def _callback(percent: float, message: str = None):
        percentage = int(percent * 100)
        click.echo(f"[{percentage:3d}%] {message or ''}")

    return _callback


@click.command()
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
def cli(
    source_folder: str,
    destination_path: Path,
    open_generated_pdf,
    cover_file_id: str,
    limit: int,
):
    progress_callback = make_cli_progress_callback()
    generate_songbook(
        source_folder, destination_path, limit, cover_file_id, progress_callback
    )
    if open_generated_pdf:
        click.echo(f"Opening generated songbook: {destination_path}")
        click.launch(destination_path)


cli()
