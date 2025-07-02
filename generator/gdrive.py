from typing import Generator, List, Dict, Optional
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload
from google.auth import default
from googleapiclient.discovery import build
import io


def authenticate_drive():
    creds, _ = default(
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
        ]
    )
    return build("drive", "v3", credentials=creds)


def build_property_filters(property_filters: Optional[Dict[str, str]]) -> str:
    """
    Build Google Drive API query filters for custom properties.

    Args:
        property_filters: Dict of property_name -> value pairs to filter by

    Returns:
        String of property filter conditions to append to the main query
    """
    if not property_filters:
        return ""

    filters = []
    for prop_name, prop_value in property_filters.items():
        # Escape single quotes in property values
        escaped_value = prop_value.replace("'", "\\'")
        filters.append(
            f"properties has {{ key='{prop_name}' and value='{escaped_value}' }}"
        )

    return " and " + " and ".join(filters) if filters else ""


def query_drive_files(
    drive, source_folder, limit, property_filters: Optional[Dict[str, str]] = None
):
    """
    Query Google Drive files with optional property filtering.

    Args:
        drive: Authenticated Google Drive service
        source_folder: Folder ID to search in
        limit: Maximum number of files to return
        property_filters: Optional dict of property_name -> value pairs to filter by
    """
    base_query = f"'{source_folder}' in parents and trashed = false"
    property_query = build_property_filters(property_filters)
    query = base_query + property_query

    click.echo(f"Executing Drive API query: {query}")
    if property_filters:
        click.echo(f"Filtering by properties: {property_filters}")

    files = []
    page_token = None
    while True:
        resp = (
            drive.files()
            .list(
                q=query,
                pageSize=limit if limit else 1000,
                fields="nextPageToken, files(id,name,properties)",
                orderBy="name_natural",
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token or (limit and len(files) >= limit):
            break
    return files[:limit] if limit else files


def stream_file_bytes(drive, files: List[dict], cache) -> Generator[bytes, None, None]:
    """
    Generator that yields the bytes of each file.
    Files are fetched from cache if available, otherwise downloaded from Drive.
    """
    for f in files:
        yield download_file_bytes(drive, f, cache)


def download_file_bytes(drive, file: Dict[str, str], cache) -> bytes:
    """
    Fetches the PDF export of a Google Doc, using a LocalStorageCache.
    Only re-downloads if remote modifiedTime is newer than the cached file.
    Returns the bytes of the file.
    """
    file_id = file["id"]
    file_name = file["name"]

    cache_key = f"song-sheets/{file_id}.pdf"

    # 1) Get the remote modified timestamp
    details = drive.files().get(fileId=file_id, fields="modifiedTime").execute()
    remote_ts = datetime.fromisoformat(details["modifiedTime"].replace("Z", "+00:00"))

    # 2) Attempt cache lookup with freshness check
    cached = cache.get(cache_key, newer_than=remote_ts)
    if cached:
        click.echo(f"Using cached version of {file_name} (ID: {file_id})")
        return cached

    # 3) Cache miss or stale: export from Drive into memory
    click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
    request = drive.files().export_media(fileId=file_id, mimeType="application/pdf")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    pdf_data = buffer.getvalue()

    # 4) Store into cache and return the bytes
    cache.put(cache_key, pdf_data)
    return pdf_data
