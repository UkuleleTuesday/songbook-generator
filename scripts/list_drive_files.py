#!/usr/bin/env python

import click
from google.auth import default
from google.oauth2 import service_account
from googleapiclient.discovery import build
import humanize


def authenticate_drive(key_file_path=None, delete_mode=False):
    """Authenticate with Google Drive API."""
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata",
    ]
    if delete_mode:
        # Broader scope is needed for deletion
        scopes = ["https://www.googleapis.com/auth/drive"]

    if key_file_path:
        creds = service_account.Credentials.from_service_account_file(
            key_file_path, scopes=scopes
        )
    else:
        creds, _ = default(scopes=scopes)
    return build("drive", "v3", credentials=creds), creds


@click.command(
    help="List all files in Google Drive and calculate total size for the authenticated user."
)
@click.option(
    "--service-account-key",
    "key_file_path",
    type=click.Path(exists=True),
    help="Path to a service account key file for authentication.",
)
@click.option(
    "--delete-files",
    is_flag=True,
    help="DANGEROUS: Interactively prompt to delete all listed files.",
)
def list_drive_files(key_file_path, delete_files):
    """
    Lists all files in Google Drive for the authenticated user,
    and calculates the total size.
    """
    drive, creds = authenticate_drive(key_file_path, delete_mode=delete_files)

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
    all_files = []

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

        files_page = response.get("files", [])
        all_files.extend(files_page)
        for file in files_page:
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

    if delete_files and all_files:
        click.echo("\n" + "=" * 40, err=True)
        click.echo("DANGER: Deletion mode is enabled.", err=True)
        click.echo(
            f"You are about to PERMANENTLY DELETE {len(all_files)} files.", err=True
        )
        confirmation_phrase = "yes I want to delete these files"
        click.echo(f"To confirm, please type the following phrase:", err=True)
        click.echo(f"  '{confirmation_phrase}'\n", err=True)
        response = click.prompt("Confirmation", type=str)

        if response == confirmation_phrase:
            click.echo("\nDELETING FILES...")
            deleted_count = 0
            error_count = 0
            for file in all_files:
                try:
                    drive.files().delete(fileId=file["id"]).execute()
                    click.echo(f"  ✓ Deleted: {file['name']} (ID: {file['id']})")
                    deleted_count += 1
                except Exception as e:
                    click.echo(
                        f"  ✗ FAILED to delete: {file['name']} (ID: {file['id']}) - {e}",
                        err=True,
                    )
                    error_count += 1
            click.echo("\nDeletion Summary:")
            click.echo(f"  Successfully deleted: {deleted_count}")
            click.echo(f"  Failed to delete: {error_count}")
        else:
            click.echo("Deletion cancelled. No files were deleted.")


if __name__ == "__main__":
    list_drive_files()
