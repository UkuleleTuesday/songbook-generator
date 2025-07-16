#!/usr/bin/env python

import click
from google.auth import default
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def authenticate_drive(key_file_path=None):
    """Authenticate with Google Drive and Docs APIs."""
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents.readonly",
    ]
    if key_file_path:
        creds = service_account.Credentials.from_service_account_file(
            key_file_path, scopes=scopes
        )
    else:
        creds, _ = default(scopes=scopes)

    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    return drive_service, docs_service


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
        drive, docs = authenticate_drive(key_file_path)
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

    # --- Test 3: Read template and write to new file ---
    new_doc_id = None
    if template_id:
        click.echo(
            f"\n--- Running Test 3: Read template and write to new doc ---"
        )
        try:
            # Step 1: Read the template document's title
            template_doc = docs.documents().get(documentId=template_id).execute()
            template_title = template_doc.get("title", "Untitled")
            click.secho(
                f"  - SUCCESS: Read template (ID: {template_id}), title: '{template_title}'",
                fg="green",
            )

            # Step 2: Create a new blank document to act as the destination
            destination_folder_id = parent_folder_id or (
                drive.files().get(fileId="root", fields="id").execute()["id"]
            )
            file_metadata = {
                "name": f"Manual Copy of {template_title}",
                "mimeType": "application/vnd.google-apps.document",
                "parents": [destination_folder_id],
            }
            new_doc = (
                drive.files().create(body=file_metadata, fields="id, name").execute()
            )
            new_doc_id = new_doc.get("id")
            click.secho(
                f"  - SUCCESS: Created new blank doc '{new_doc.get('name')}' (ID: {new_doc_id})",
                fg="green",
            )
            # This just proves we can read the template and create a new file owned by us.
            # A full content copy is complex, so we'll stop here for this test.
            click.secho(
                "SUCCESS: Read-and-create test successful. This suggests a viable workaround.",
                fg="green",
            )

        except HttpError as error:
            click.secho("FAILURE: Could not read or create file.", fg="red", err=True)
            click.secho(f"  - Details: {error.content.decode()}", fg="red", err=True)
        except Exception as e:
            click.secho(f"An unexpected error occurred: {e}", fg="red", err=True)

    # --- Cleanup ---
    if created_file_id or copied_file_id or new_doc_id:
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
        if new_doc_id:
            try:
                drive.files().delete(fileId=new_doc_id).execute()
                click.secho(
                    f"Successfully deleted test doc (ID: {new_doc_id}).",
                    fg="green",
                )
            except HttpError as error:
                click.secho(
                    f"FAILED to delete test doc (ID: {new_doc_id}). Please remove it manually. Error: {error}",
                    fg="yellow",
                    err=True,
                )


if __name__ == "__main__":
    drive_write_test()
