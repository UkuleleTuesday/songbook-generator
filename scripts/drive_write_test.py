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
    help="Tests write access to Google Drive by creating a small test file."
)
@click.option(
    "--service-account-key",
    "key_file_path",
    type=click.Path(exists=True),
    help="Path to a service account key file for authentication.",
)
def drive_write_test(key_file_path):
    """
    Attempts to create a small, empty file in the root of the
    authenticated user's Google Drive to test for write permissions
    and quota issues.
    """
    try:
        drive = authenticate_drive(key_file_path)
        click.echo("Authentication successful. Attempting to create test file...")
    except Exception as e:
        click.echo(f"Error during authentication: {e}", err=True)
        return

    file_metadata = {
        "name": "songbook-generator-write-test.txt",
        "mimeType": "text/plain",
    }
    file_id = None

    try:
        # Create the file in the root of "My Drive"
        # Not specifying 'parents' places it in the root.
        file = drive.files().create(body=file_metadata, fields="id, name").execute()
        file_id = file.get("id")
        click.secho(
            f"\nSUCCESS: Successfully created file '{file.get('name')}' with ID: {file_id}",
            fg="green",
        )

    except HttpError as error:
        click.secho(
            f"\nFAILURE: Could not create file. The API returned an error:",
            fg="red",
            err=True,
        )
        click.secho(f"  - Status: {error.status_code}", fg="red", err=True)
        click.secho(f"  - Reason: {error.reason}", fg="red", err=True)
        # The error response body often contains the detailed error message.
        click.secho(f"  - Details: {error.content.decode()}", fg="red", err=True)
        return
    except Exception as e:
        click.secho(f"\nAn unexpected error occurred: {e}", fg="red", err=True)
        return

    # --- Cleanup ---
    if file_id:
        click.echo("\nAttempting to clean up by deleting the test file...")
        try:
            drive.files().delete(fileId=file_id).execute()
            click.secho("Cleanup successful: Test file deleted.", fg="green")
        except HttpError as error:
            click.secho(
                f"Cleanup FAILED: Could not delete test file (ID: {file_id}). "
                f"Please delete it manually. Error: {error}",
                fg="yellow",
                err=True,
            )


if __name__ == "__main__":
    drive_write_test()
