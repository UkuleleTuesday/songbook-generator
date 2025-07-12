#!/usr/bin/env python

import click
import google.auth
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import humanize
import os


def authenticate_drive():
    """Authenticate with Google Drive and return the service object."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", [])
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                ["https://www.googleapis.com/auth/drive.readonly"],
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

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
    click.echo("Authenticated with Google Drive successfully.")

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
