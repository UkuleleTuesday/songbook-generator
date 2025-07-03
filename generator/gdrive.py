from typing import Generator, List, Dict, Optional, Union
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
from google.auth import default
from googleapiclient.discovery import build
import io

from filters import PropertyFilter, FilterGroup


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

    Returns:
        List of files, or empty list if error occurs
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
        try:
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

        except HttpError as e:
            error_code = e.resp.status if e.resp else "unknown"
            error_msg = str(e)

            if error_code == 403:
                click.echo(
                    f"Permission denied accessing folder {source_folder}. Check your access rights."
                )
            elif error_code == 404:
                click.echo(f"Folder {source_folder} not found. Check the folder ID.")
            elif error_code == 429:
                click.echo("API quota exceeded. Please try again later.")
            else:
                click.echo(f"Error querying Drive API (HTTP {error_code}): {error_msg}")

            # Return partial results if we have any, otherwise empty list
            break

        except Exception as e:
            click.echo(f"Unexpected error querying Drive files: {str(e)}")
            break

    return files[:limit] if limit else files


def query_drive_files_with_client_filter(
    drive,
    source_folder,
    limit,
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
):
    """
    Query Google Drive files and apply client-side filtering.

    Args:
        drive: Authenticated Google Drive service
        source_folder: Folder ID to search in
        limit: Maximum number of files to return after filtering
        client_filter: Client-side filter to apply after fetching files

    Returns:
        List of files matching the client-side filter
    """
    # First, get all files from Drive (no server-side property filtering)
    click.echo("Fetching all files from Drive for client-side filtering...")
    all_files = query_drive_files(drive, source_folder, None, None)

    if not client_filter:
        return all_files[:limit] if limit else all_files

    # Apply client-side filtering
    filtered_files = []
    for file in all_files:
        properties = file.get("properties", {})
        if client_filter.matches(properties):
            filtered_files.append(file)
            if limit and len(filtered_files) >= limit:
                break

    click.echo(
        f"Client-side filtering: {len(filtered_files)} files match out of {len(all_files)} total"
    )
    return filtered_files


def stream_file_bytes(drive, files: List[dict], cache) -> Generator[bytes, None, None]:
    """
    Generator that yields the bytes of each file.
    Files are fetched from cache if available, otherwise downloaded from Drive.
    """
    for f in files:
        with download_file_stream(drive, f, cache) as stream:
            yield stream.getvalue()


def download_file_stream(drive, file: Dict[str, str], cache) -> io.BytesIO:
    """
    Fetches the PDF export of a Google Doc, using a LocalStorageCache.
    Only re-downloads if remote modifiedTime is newer than the cached file.
    Returns a BytesIO stream of the file.
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
        return io.BytesIO(cached)

    # 3) Cache miss or stale: export from Drive into memory
    click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
    request = drive.files().export_media(fileId=file_id, mimeType="application/pdf")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    pdf_data = buffer.getvalue()

    # 4) Store into cache and return a new BytesIO stream
    cache.put(cache_key, pdf_data)
    return io.BytesIO(pdf_data)


def download_file_bytes(drive, file: Dict[str, str], cache) -> bytes:
    """
    Legacy function for backward compatibility.
    Fetches the PDF export and returns raw bytes.
    """
    with download_file_stream(drive, file, cache) as stream:
        return stream.getvalue()
