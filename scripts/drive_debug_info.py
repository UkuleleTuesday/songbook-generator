#!/usr/bin/env python

import click
import humanize
from google.auth import default
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def authenticate_drive(key_file_path=None):
    """Authenticate with Google Drive API using read-only scopes."""
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    if key_file_path:
        creds = service_account.Credentials.from_service_account_file(
            key_file_path, scopes=scopes
        )
    else:
        creds, _ = default(scopes=scopes)
    return build("drive", "v3", credentials=creds), creds


def print_section(title):
    """Print a formatted section header."""
    click.echo("\n" + "=" * 60)
    click.echo(f" {title}")
    click.echo("=" * 60)


@click.command(help="Get diagnostic information about a Google Drive account.")
@click.option(
    "--service-account-key",
    "key_file_path",
    type=click.Path(exists=True),
    help="Path to a service account key file for authentication.",
)
def drive_debug_info(key_file_path):
    """
    Gathers and displays comprehensive diagnostic information from the
    Google Drive API to help debug quota and access issues.
    """
    try:
        drive, creds = authenticate_drive(key_file_path)
    except Exception as e:
        click.echo(f"Error during authentication: {e}", err=True)
        return

    # --- 1. Authentication Info ---
    print_section("1. Authentication Details")
    if hasattr(creds, "service_account_email"):
        click.echo("  Type: Service Account")
        click.echo(f"  Email: {creds.service_account_email}")
    elif hasattr(creds, "token"):
        click.echo("  Type: User Credentials (Application Default Credentials)")
    else:
        click.echo(f"  Type: {type(creds)}")
    click.echo(f"  Scopes: {creds.scopes if creds.scopes else 'Not specified'}")

    # --- 2. User & Quota Info from about.get ---
    print_section("2. Account & Storage Quota Information")
    try:
        about = drive.about().get(fields="user,storageQuota,maxUploadSize").execute()
        user_info = about.get("user", {})
        click.echo("  User Display Name: " + user_info.get("displayName", "N/A"))
        click.echo("  User Email Address: " + user_info.get("emailAddress", "N/A"))

        storage_quota = about.get("storageQuota", {})
        if storage_quota:
            limit = int(storage_quota.get("limit", 0))
            usage = int(storage_quota.get("usage", 0))
            usage_in_drive = int(storage_quota.get("usageInDrive", 0))
            usage_in_trash = int(storage_quota.get("usageInDriveTrash", 0))
            free_space = limit - usage if limit > 0 else "N/A"

            click.echo("\n  Storage Quota:")
            click.echo(f"    - Limit: {humanize.naturalsize(limit) if limit > 0 else 'Unlimited'}")
            click.echo(f"    - Total Used: {humanize.naturalsize(usage)}")
            if free_space != "N/A":
                click.echo(f"    - Free Space: {humanize.naturalsize(free_space)}")
            click.echo(f"    - Used in Drive: {humanize.naturalsize(usage_in_drive)}")
            click.echo(f"    - Used in Trash: {humanize.naturalsize(usage_in_trash)}")
            if limit > 0:
                percent_used = (usage / limit) * 100
                click.echo(f"    - Percentage Used: {percent_used:.2f}%")
        else:
            click.echo("  Storage Quota: No information returned.")

        max_upload = int(about.get("maxUploadSize", 0))
        click.echo("\n  File Upload Limits:")
        click.echo(f"    - Max Upload Size: {humanize.naturalsize(max_upload)}")

    except HttpError as e:
        click.echo(f"  Could not retrieve 'about' info: {e}", err=True)

    # --- 3. File Counts ---
    print_section("3. File & Folder Counts (owned by this account)")
    file_count = 0
    folder_count = 0
    total_size = 0
    page_token = None
    click.echo("  Fetching file list (this may take a moment)...", nl=False)
    while True:
        try:
            response = (
                drive.files()
                .list(
                    q="'me' in owners and trashed=false",
                    fields="nextPageToken, files(size, mimeType)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            files_page = response.get("files", [])
            for f in files_page:
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    folder_count += 1
                else:
                    file_count += 1
                    total_size += int(f.get("size", "0"))

            page_token = response.get("nextPageToken", None)
            if page_token is None:
                break
        except HttpError as e:
            click.echo(f"\nAn error occurred fetching files: {e}", err=True)
            break
    click.echo(" Done.")

    click.echo(f"  Total Files (non-folders): {file_count}")
    click.echo(f"  Total Folders: {folder_count}")
    click.echo(f"  Total Size of Owned Files: {humanize.naturalsize(total_size)}")

    # --- 4. Shared Drive Info ---
    print_section("4. Shared Drive Information")
    try:
        response = drive.drives().list(pageSize=100).execute()
        shared_drives = response.get("drives", [])
        if shared_drives:
            click.echo(f"  Found {len(shared_drives)} shared drives:")
            for d in shared_drives:
                click.echo(f"    - Name: {d['name']} (ID: {d['id']})")
        else:
            click.echo("  No shared drives found for this account.")
    except HttpError as e:
        click.echo(f"  Could not list shared drives: {e}", err=True)
        click.echo("  (Service account may need 'Shared Drive' support enabled in its configuration).")

    # --- 5. API Quota Info ---
    print_section("5. API Usage Quotas")
    click.echo("  API usage quotas (e.g., requests per minute) are not exposed by the API.")
    click.echo("  To check usage against limits, visit the Google Cloud Console:")
    click.echo("  https://console.cloud.google.com/apis/dashboard")
    click.echo("  Navigate to 'Google Drive API' -> 'Quotas'.")
    click.echo("  Note: Free-tier user quotas are per-user, not per-project.")


if __name__ == "__main__":
    drive_debug_info()
