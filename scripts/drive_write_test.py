#!/usr/bin/env python

import click
from google.auth import default
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def authenticate_drive(key_file_path=None):
    """Authenticate with Google Drive API with full drive access scope."""
    # Full 'drive' scope is required to create and delete files.
    scopes = ["https://www.googleapis.com/auth/drive"]
    if key_file_path:
        creds = service_account.Credentials.from_service_account_file(
            key_file_path, scopes=scopes
        )
    else:
        creds, _ = default(scopes=scopes)
    return build("drive", "v3", credentials=creds)


@click.command(
    help="Tests write access to Google Drive by creating and copying files."
)
@click.option(
    "--service-account-key",
    "key_file_path",
    type=click.Path(exists=True),
    help="Path to a service account key file for authentication.",
)
@click.option(
    "--template-id",
    "template_id",
    type=str,
    help="Google Drive file ID of a template document to test copying.",
    default=None,
)
@click.option(
    "--parent-folder-id",
    "parent_folder_id",
    type=str,
    help="Google Drive folder ID to use as the parent for the copied file.",
    default=None,
)
def drive_write_test(key_file_path, template_id, parent_folder_id):
    """
    Tests write permissions by creating an empty file and optionally
    by copying a template file.
    """
    try:
        drive = authenticate_drive(key_file_path)
        click.echo("Authentication successful.")
    except Exception as e:
        click.echo(f"Error during authentication: {e}", err=True)
        return

    # --- Test 1: Create a new file ---
    click.echo("\n--- Running Test 1: Create new file ---")
    created_file_id = None
    try:
        file_metadata = {
            "name": "songbook-generator-write-test.txt",
            "mimeType": "text/plain",
        }
        file = drive.files().create(body=file_metadata, fields="id, name").execute()
        created_file_id = file.get("id")
        click.secho(
            f"SUCCESS: Successfully created file '{file.get('name')}' with ID: {created_file_id}",
            fg="green",
        )
    except HttpError as error:
        click.secho("FAILURE: Could not create file.", fg="red", err=True)
        click.secho(f"  - Details: {error.content.decode()}", fg="red", err=True)
    except Exception as e:
        click.secho(f"An unexpected error occurred: {e}", fg="red", err=True)

    # --- Test 2: Copy a template file ---
    copied_file_id = None
    if template_id:
        click.echo(f"\n--- Running Test 2: Copy template file (ID: {template_id}) ---")
        try:
            destination_folder_id = parent_folder_id
            if not destination_folder_id:
                # If no parent is specified, default to the root of "My Drive"
                destination_folder_id = (
                    drive.files().get(fileId="root", fields="id").execute()["id"]
                )

            copy_metadata = {
                "name": f"Copy of {template_id}",
                "parents": [destination_folder_id],
            }
            copy = (
                drive.files()
                .copy(fileId=template_id, body=copy_metadata, fields="id, name")
                .execute()
            )
            copied_file_id = copy.get("id")
            click.secho(
                f"SUCCESS: Successfully copied file. New file is '{copy.get('name')}' with ID: {copied_file_id}",
                fg="green",
            )
        except HttpError as error:
            click.secho("FAILURE: Could not copy file.", fg="red", err=True)
            click.secho(f"  - Details: {error.content.decode()}", fg="red", err=True)
        except Exception as e:
            click.secho(f"An unexpected error occurred: {e}", fg="red", err=True)

    # --- Cleanup ---
    if created_file_id or copied_file_id:
        click.echo("\n--- Cleanup ---")
        if created_file_id:
            try:
                drive.files().delete(fileId=created_file_id).execute()
                click.secho(
                    f"Successfully deleted created file (ID: {created_file_id}).",
                    fg="green",
                )
            except HttpError as error:
                click.secho(
                    f"FAILED to delete created file (ID: {created_file_id}). Please remove it manually. Error: {error}",
                    fg="yellow",
                    err=True,
                )
        if copied_file_id:
            try:
                drive.files().delete(fileId=copied_file_id).execute()
                click.secho(
                    f"Successfully deleted copied file (ID: {copied_file_id}).",
                    fg="green",
                )
            except HttpError as error:
                click.secho(
                    f"FAILED to delete copied file (ID: {copied_file_id}). Please remove it manually. Error: {error}",
                    fg="yellow",
                    err=True,
                )


if __name__ == "__main__":
    drive_write_test()
