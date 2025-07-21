from typing import Generator, List, Dict, Optional, Union
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io
from opentelemetry import trace

from ..worker.filters import FilterGroup, PropertyFilter


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
    drive,
    source_folder,
    property_filters: Optional[Dict[str, str]] = None,
    modified_after: Optional[datetime] = None,
):
    """
    Query Google Drive files with optional property filtering.

    Args:
        drive: Authenticated Google Drive service
        source_folder: Folder ID to search in
        property_filters: Optional dict of property_name -> value pairs to filter by

    Returns:
        List of files, or empty list if error occurs
    """
    base_query = f"'{source_folder}' in parents and trashed = false"
    property_query = build_property_filters(property_filters)
    query = base_query + property_query

    if modified_after:
        # Format for Drive API query, e.g., '2023-08-01T12:00:00'
        ts_str = modified_after.isoformat()
        query += f" and modifiedTime > '{ts_str}'"

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
                    pageSize=1000,
                    fields="nextPageToken, files(id,name,properties,mimeType)",
                    orderBy="name_natural",
                    pageToken=page_token,
                )
                .execute()
            )

            files.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")

            if not page_token:
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

    return files


def query_drive_files_with_client_filter(
    drive,
    source_folder,
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
):
    """
    Query Google Drive files and apply client-side filtering.

    Args:
        drive: Authenticated Google Drive service
        source_folder: Folder ID to search in
        client_filter: Client-side filter to apply after fetching files

    Returns:
        List of files matching the client-side filter
    """
    # First, get all files from Drive (no server-side property filtering)
    click.echo("Fetching all files from Drive for client-side filtering...")
    all_files = query_drive_files(drive, source_folder, None)

    if not client_filter:
        return all_files

    # Apply client-side filtering
    filtered_files = []
    for file in all_files:
        properties = file.get("properties", {})
        if client_filter.matches(properties):
            filtered_files.append(file)

    click.echo(
        f"Client-side filtering: {len(filtered_files)} files match out of {len(all_files)} total"
    )
    return filtered_files


def get_files_metadata_by_ids(drive, file_ids: List[str], progress_step=None):
    """
    Get file metadata by their Google Drive IDs.

    Args:
        drive: Authenticated Google Drive service
        file_ids: List of Google Drive file IDs
        progress_step: Optional progress step for reporting

    Returns:
        List of file dictionaries with metadata
    """
    files = []
    for file_id in file_ids:
        try:
            # Get file metadata from Drive
            file_metadata = (
                drive.files()
                .get(fileId=file_id, fields="id,name,properties,mimeType")
                .execute()
            )
            file_dict = {
                "id": file_id,
                "name": file_metadata.get("name", f"file_{file_id}"),
                "properties": file_metadata.get("properties", {}),
            }
            files.append(file_dict)

            if progress_step:
                progress_step.increment(
                    1 / len(file_ids),
                    f"Retrieved metadata for {file_dict['name']}",
                )
        except HttpError as e:
            click.echo(f"Warning: Could not retrieve file {file_id}: {e}")
            if progress_step:
                progress_step.increment(
                    1 / len(file_ids),
                    f"Failed to retrieve file {file_id}",
                )

    return files


def stream_file_bytes(drive, files: List[dict], cache) -> Generator[bytes, None, None]:
    """
    Generator that yields the bytes of each file.
    Files are fetched from cache if available, otherwise downloaded from Drive.
    """
    for f in files:
        with download_file_stream(drive, f, cache) as stream:
            yield stream.getvalue()


def download_file(
    drive,
    file_id: str,
    file_name: str,
    cache,
    cache_prefix: str,
    mime_type: str = "application/pdf",
    export: bool = True,
) -> bytes:
    """
    Generic file downloader with caching.

    Can either download a file directly or export a Google Doc to a specific format.
    """
    span = trace.get_current_span()
    cache_key = f"{cache_prefix}/{file_id}.pdf"
    span.set_attribute("cache.key", cache_key)

    details = drive.files().get(fileId=file_id, fields="modifiedTime").execute()
    remote_ts = datetime.fromisoformat(details["modifiedTime"].replace("Z", "+00:00"))
    span.set_attribute("gdrive.remote_modified_time", str(remote_ts))

    try:
        cached = cache.get(cache_key, newer_than=remote_ts)
        if cached:
            span.set_attribute("cache.hit", True)
            click.echo(f"Using cached version of {file_name} (ID: {file_id})")
            return cached
    except FileNotFoundError:
        # This is an expected cache miss for local storage, not an error.
        pass
    except Exception as e:  # noqa: BLE001 - Safely ignore cache errors and re-download
        span.set_attribute("cache.error", str(e))
        click.echo(
            f"Cache lookup failed for {file_name} (ID: {file_id}): {e}. Will re-download."
        )

    span.set_attribute("cache.hit", False)
    click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
    if export:
        request = drive.files().export_media(fileId=file_id, mimeType=mime_type)
    else:
        request = drive.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    data = buffer.getvalue()
    # GCSFS supports setting metadata on upload via `metadata` kwarg.
    # The local file system fsspec impl does not support this.
    try:
        cache.put(cache_key, data, metadata={"gdrive-file-name": file_name})
    except TypeError:
        # Fallback for filesystems that don't support metadata
        cache.put(cache_key, data)
    return data


def download_file_stream(drive, file: Dict[str, str], cache) -> io.BytesIO:
    """
    Fetches the PDF export of a Google Doc, using a LocalStorageCache.
    Only re-downloads if remote modifiedTime is newer than the cached file.
    Returns a BytesIO stream of the file.
    """
    # Google Docs need to be exported, while regular PDFs can be downloaded directly.
    mime_type = file.get("mimeType")
    should_export = mime_type == "application/vnd.google-apps.document"

    pdf_data = download_file(
        drive,
        file["id"],
        file["name"],
        cache,
        "song-sheets",
        "application/pdf",
        export=should_export,
    )
    return io.BytesIO(pdf_data)


def download_file_bytes(drive, file: Dict[str, str], cache) -> bytes:
    """
    Legacy function for backward compatibility.
    Fetches the PDF export and returns raw bytes.
    """
    with download_file_stream(drive, file, cache) as stream:
        return stream.getvalue()
