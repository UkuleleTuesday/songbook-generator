import functools

import click

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient


def make_cli_progress_callback():
    """Return a callback that displays progress updates to the console."""

    def _callback(percent: float, message: str = None):
        percentage = int(percent * 100)
        click.echo(f"[{percentage:3d}%] {message or ''}")

    return _callback


def global_options(f):
    """Decorator to apply global options to a command."""
    options = [
        click.option(
            "--log-level",
            default="INFO",
            type=click.Choice(
                ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                case_sensitive=False,
            ),
            help="Set the logging level.",
        )
    ]
    return functools.reduce(lambda x, opt: opt(x), options, f)


def _resolve_file_id(gdrive_client: GoogleDriveClient, file_identifier: str) -> str:
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
    found_files = gdrive_client.search_files_by_name(file_identifier, source_folders)

    if not found_files:
        click.echo(f"Error: No file found matching '{file_identifier}'.", err=True)
        raise click.Abort()

    if len(found_files) > 1:
        click.echo(
            f"Error: Found multiple files matching '{file_identifier}'. "
            "Please be more specific or use a file ID.",
            err=True,
        )
        for f in found_files:
            click.echo(f"  - {f.name} (ID: {f.id})", err=True)
        raise click.Abort()

    file_id = found_files[0].id
    click.echo(f"Found file: {found_files[0].name} (ID: {file_id})")
    return file_id
