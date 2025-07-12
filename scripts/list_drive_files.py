#!/usr/bin/env python

import click
from google.auth import default
from googleapiclient.discovery import build
import humanize


def authenticate_drive():
    """Authenticate with Google Drive API."""
    creds, _ = default(
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.metadata",
        ]
    )
    return build("drive", "v3", credentials=creds)


@click.command(
    help="List all files in Google Drive and calculate total size for the authenticated user."
)
def list_drive_files():
    """
    Lists all files in Google Drive for the authenticated user,
    and calculates the total size.
    """
    drive = authenticate_drive()
    creds, _ = default()
    click.echo("=" * 40)
    click.echo("Authentication Details:")
    if hasattr(creds, "service_account_email"):
        click.echo(f"  Type: Service Account")
        click.echo(f"  Email: {creds.service_account_email}")
    elif hasattr(creds, "token"):
        click.echo(f"  Type: User Credentials")
        try:
            about = drive.about().get(fields="user").execute()
            user_info = about.get("user")
            if user_info:
                click.echo(f"  User: {user_info.get('displayName')}")
                click.echo(f"  Email: {user_info.get('emailAddress')}")
        except Exception as e:
            click.echo(f"  Could not retrieve user info: {e}")
    else:
        click.echo(f"  Type: {type(creds)}")
    click.echo(f"  Scopes: {creds.scopes}")
    click.echo("=" * 40)

    total_size = 0
    file_count = 0
    page_token = None

    click.echo("Fetching file list...")

    while True:
        try:
            response = (
                drive.files()
                .list(
                    q="'me' in owners and trashed=false",
                    fields="nextPageToken, files(id, name, size, mimeType)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
        except Exception as e:
            click.echo(f"An error occurred: {e}", err=True)
            break

        files = response.get("files", [])
        for file in files:
            file_count += 1
            size_str = file.get("size", "0")
            size = int(size_str)
            total_size += size
            human_size = (
                humanize.naturalsize(size) if size > 0 else "0 B (Folder/Shortcut)"
            )
            click.echo(
                f" - {file['name']} ({file['mimeType']}) - Size: {human_size} (ID: {file['id']})"
            )

        page_token = response.get("nextPageToken", None)
        if page_token is None:
            break

    click.echo("\n" + "=" * 20)
    click.echo("Summary:")
    click.echo(f"Total number of files: {file_count}")
    click.echo(f"Total size of all files: {humanize.naturalsize(total_size)}")
    click.echo("=" * 20)


if __name__ == "__main__":
    list_drive_files()
