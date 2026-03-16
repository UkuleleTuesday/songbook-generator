import functools

import click

from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..worker.pdf import init_services
from .utils import _resolve_file_id


@click.group()
def specialbooks():
    """Manage the specialbooks tag for songs (controls which editions a song appears in)."""


def edition_management_command(func):
    """Decorator to handle boilerplate for edition management commands."""

    @functools.wraps(func)
    def wrapper(edition_name, file_identifier, **kwargs):
        settings = get_settings()
        credential_config = settings.google_cloud.credentials.get(
            "songbook-metadata-writer"
        )
        if not credential_config:
            click.echo(
                "Error: credential config 'songbook-metadata-writer' not found.",
                err=True,
            )
            raise click.Abort()

        drive, cache = init_services(
            scopes=credential_config.scopes,
            target_principal=credential_config.principal,
        )
        gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

        file_id = _resolve_file_id(gdrive_client, file_identifier)
        properties = gdrive_client.get_file_properties(file_id)
        if properties is None:
            raise click.Abort()

        special_books_raw = properties.get("specialbooks", "")
        current_editions = {
            s.strip() for s in special_books_raw.split(",") if s.strip()
        }

        # Pass control to the decorated command function
        new_editions = func(current_editions, edition_name, file_id=file_id, **kwargs)

        # If the command returns None, it's a no-op (e.g., already in edition)
        if new_editions is None:
            return

        # Persist the changes
        new_value = ",".join(sorted(list(new_editions)))
        if gdrive_client.set_file_property(file_id, "specialbooks", new_value):
            click.echo(
                f"Successfully updated editions. New 'specialbooks' value: '{new_value}'"
            )
        else:
            click.echo("Failed to update editions.", err=True)
            raise click.Abort()

    return wrapper


@specialbooks.command(name="add-song")
@click.argument("edition_name")
@click.argument("file_identifier")
@edition_management_command
def add_song_to_edition(current_editions, edition_name, **kwargs):
    """Adds a song to a specific songbook edition (specialbooks tag)."""
    if edition_name in current_editions:
        click.echo(f"Song is already in the '{edition_name}' edition.")
        return None  # Signal no-op

    current_editions.add(edition_name)
    return current_editions


@specialbooks.command(name="remove-song")
@click.argument("edition_name")
@click.argument("file_identifier")
@edition_management_command
def remove_song_from_edition(current_editions, edition_name, **kwargs):
    """Removes a song from a specific songbook edition (specialbooks tag)."""
    if edition_name not in current_editions:
        click.echo(f"Song is not in the '{edition_name}' edition. No changes made.")
        return None  # Signal no-op

    current_editions.remove(edition_name)
    return current_editions


@specialbooks.command(name="list")
@click.argument("file_identifier")
def list_song_editions(file_identifier):
    """Lists all editions a song belongs to."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-reader"
    )
    if not credential_config:
        # Fallback to writer if reader isn't defined
        credential_config = settings.google_cloud.credentials.get(
            "songbook-metadata-writer"
        )

    if not credential_config:
        click.echo(
            "Error: No suitable credential config found.",
            err=True,
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)
    properties = gdrive_client.get_file_properties(file_id)
    if properties is None:
        raise click.Abort()

    special_books_raw = properties.get("specialbooks", "")
    current_editions = {s.strip() for s in special_books_raw.split(",") if s.strip()}

    if not current_editions:
        click.echo("Song does not belong to any editions.")
    else:
        click.echo("Song is in the following editions:")
        for edition in sorted(list(current_editions)):
            click.echo(f"- {edition}")
