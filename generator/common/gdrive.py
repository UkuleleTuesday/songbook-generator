from typing import Generator, List, Dict, Optional, Union
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io
from opentelemetry import trace
from googleapiclient.discovery import build

from .filters import FilterGroup, PropertyFilter
from .fonts import normalize_pdf_fonts
from ..worker.models import File
from google.auth import credentials


def client(credentials: credentials.Credentials):
    """Build a Google Drive API client from credentials."""
    return build("drive", "v3", credentials=credentials)


def _build_property_filters(property_filters: Optional[Dict[str, str]]) -> str:
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


class GoogleDriveClient:
    def __init__(
        self, cache, credentials: Optional[credentials.Credentials] = None, drive=None
    ):
        if drive:
            self.drive = drive
        elif credentials:
            self.drive = client(credentials)
        else:
            raise ValueError("Either 'credentials' or 'drive' must be provided.")
        self.cache = cache

    def search_files_by_name(
        self, file_name: str, source_folders: List[str]
    ) -> List[File]:
        """Search for files by name across multiple folders."""
        parent_queries = [f"'{folder_id}' in parents" for folder_id in source_folders]
        # Format for Drive API query, e.g., "name contains 'My Song'"
        escaped_file_name = file_name.replace("'", "\\'")
        query = f"name contains '{escaped_file_name}' and ({' or '.join(parent_queries)}) and trashed = false"

        click.echo(f"Searching for file matching '{file_name}'...")
        click.echo(f"Executing Drive API query: {query}")

        try:
            resp = (
                self.drive.files()
                .list(
                    q=query,
                    pageSize=10,  # Limit to a reasonable number for this use case
                    fields="files(id,name,parents,properties,mimeType)",
                )
                .execute()
            )
            files = [
                File(
                    id=f["id"],
                    name=f["name"],
                    properties=f.get("properties", {}),
                    mimeType=f.get("mimeType"),
                    parents=f.get("parents", []),
                )
                for f in resp.get("files", [])
            ]
            return files
        except HttpError as e:
            click.echo(f"Error querying Drive API: {e}", err=True)
            return []

    def query_drive_files(
        self,
        source_folder,
        property_filters: Optional[Dict[str, str]] = None,
        modified_after: Optional[datetime] = None,
    ) -> List[File]:
        """
        Query Google Drive files with optional property filtering.

        Args:
            source_folder: Folder ID to search in
            property_filters: Optional dict of property_name -> value pairs to filter by

        Returns:
            List of files, or empty list if error occurs
        """
        base_query = f"'{source_folder}' in parents and trashed = false"
        property_query = _build_property_filters(property_filters)
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
                    self.drive.files()
                    .list(
                        q=query,
                        pageSize=1000,
                        fields="nextPageToken, files(id,name,parents,properties,mimeType)",
                        orderBy="name_natural",
                        pageToken=page_token,
                    )
                    .execute()
                )

                for f in resp.get("files", []):
                    files.append(
                        File(
                            id=f["id"],
                            name=f["name"],
                            properties=f.get("properties", {}),
                            mimeType=f.get("mimeType"),
                            parents=f.get("parents", []),
                        )
                    )
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
                    click.echo(
                        f"Folder {source_folder} not found. Check the folder ID."
                    )
                elif error_code == 429:
                    click.echo("API quota exceeded. Please try again later.")
                else:
                    click.echo(
                        f"Error querying Drive API (HTTP {error_code}): {error_msg}"
                    )

                # Return partial results if we have any, otherwise empty list
                break

        return files

    def query_drive_files_with_client_filter(
        self,
        source_folder,
        client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    ) -> List[File]:
        """
        Query Google Drive files and apply client-side filtering.

        Args:
            source_folder: Folder ID to search in
            client_filter: Client-side filter to apply after fetching files

        Returns:
            List of files matching the client-side filter
        """
        # First, get all files from Drive (no server-side property filtering)
        click.echo("Fetching all files from Drive for client-side filtering...")
        all_files = self.query_drive_files(source_folder, None)

        if not client_filter:
            return all_files

        # Apply client-side filtering
        filtered_files = []
        for file in all_files:
            if client_filter.matches(file.properties):
                filtered_files.append(file)

        click.echo(
            f"Client-side filtering: {len(filtered_files)} files match out of {len(all_files)} total"
        )
        return filtered_files

    def download_file_stream(self, file: File) -> io.BytesIO:
        """
        Fetches the PDF export of a Google Doc, using a LocalStorageCache.
        Only re-downloads if remote modifiedTime is newer than the cached file.
        Returns a BytesIO stream of the file.
        """
        # Google Docs need to be exported, while regular PDFs can be downloaded directly.
        should_export = file.mimeType == "application/vnd.google-apps.document"

        pdf_data = self.download_file(
            file.id,
            file.name,
            "song-sheets",
            "application/pdf",
            export=should_export,
        )
        return io.BytesIO(pdf_data)

    def stream_file_bytes(
        self, files: List[File]
    ) -> Generator[bytes, None, None]:
        """
        Generator that yields the bytes of each file.
        Files are fetched from cache if available, otherwise downloaded from Drive.
        """
        for f in files:
            with self.download_file_stream(f) as stream:
                yield stream.getvalue()

    def download_file(
        self,
        file_id: str,
        file_name: str,
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

        details = (
            self.drive.files().get(fileId=file_id, fields="modifiedTime").execute()
        )
        remote_ts = datetime.fromisoformat(
            details["modifiedTime"].replace("Z", "+00:00")
        )
        span.set_attribute("gdrive.remote_modified_time", str(remote_ts))

        try:
            cached = self.cache.get(cache_key, newer_than=remote_ts)
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
            request = self.drive.files().export_media(
                fileId=file_id, mimeType=mime_type
            )
        else:
            request = self.drive.files().get_media(fileId=file_id)

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        data = buffer.getvalue()

        # If we exported a Google Doc to PDF, normalize its fonts before caching.
        # This reduces final songbook size significantly.
        if export and mime_type == "application/pdf":
            click.echo(f"Normalizing fonts for {file_name}...")
            try:
                data = normalize_pdf_fonts(data)
            except RuntimeError as e:
                click.echo(
                    f"Font normalization failed for {file_name} ({file_id}), caching original file. Error: {e}",
                    err=True,
                )

        # GCSFS supports setting metadata on upload via `metadata` kwarg.
        # The local file system fsspec impl does not support this.
        try:
            self.cache.put(cache_key, data, metadata={"gdrive-file-name": file_name})
        except TypeError:
            # Fallback for filesystems that don't support metadata
            self.cache.put(cache_key, data)
        return data

    def get_files_metadata_by_ids(
        self, file_ids: List[str], progress_step=None
    ) -> List[File]:
        """
        Get file metadata by their Google Drive IDs.

        Args:
            file_ids: List of Google Drive file IDs
            progress_step: Optional progress step for reporting

        Returns:
            List of file objects with metadata
        """
        files = []
        for file_id in file_ids:
            try:
                # Get file metadata from Drive
                file_metadata = (
                    self.drive.files()
                    .get(fileId=file_id, fields="id,name,properties,mimeType")
                    .execute()
                )
                file_obj = File(
                    id=file_id,
                    name=file_metadata.get("name", f"file_{file_id}"),
                    properties=file_metadata.get("properties", {}),
                    mimeType=file_metadata.get("mimeType"),
                )
                files.append(file_obj)

                if progress_step:
                    progress_step.increment(
                        1 / len(file_ids),
                        f"Retrieved metadata for {file_obj.name}",
                    )
            except HttpError as e:
                click.echo(f"Warning: Could not retrieve file {file_id}: {e}")
                if progress_step:
                    progress_step.increment(
                        1 / len(file_ids),
                        f"Failed to retrieve file {file_id}",
                    )

        return files

    def download_file_bytes(self, file: File) -> bytes:
        """
        Legacy function for backward compatibility.
        Fetches the PDF export and returns raw bytes.
        """
        with self.download_file_stream(file) as stream:
            return stream.getvalue()

    def get_file_properties(self, file_id: str) -> Optional[Dict[str, str]]:
        """
        Get custom properties for a given Google Drive file.

        Args:
            file_id: The ID of the file.

        Returns:
            A dictionary of properties, or None if the file is not found.
        """
        try:
            file_metadata = (
                self.drive.files().get(fileId=file_id, fields="properties").execute()
            )
            return file_metadata.get("properties", {})
        except HttpError as e:
            if e.resp.status == 404:
                click.echo(f"Error: File with ID '{file_id}' not found.", err=True)
                return None
            click.echo(f"An API error occurred: {e}", err=True)
            return None

    def set_file_property(self, file_id: str, key: str, value: str) -> bool:
        """
        Sets a custom property on a Google Drive file.

        Args:
            file_id: The ID of the file to update.
            key: The property key to set.
            value: The property value to set.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # First, get the current properties to not overwrite them
            file_metadata = (
                self.drive.files().get(fileId=file_id, fields="properties").execute()
            )
            properties = file_metadata.get("properties", {})
            properties[key] = value

            body = {"properties": properties}
            self.drive.files().update(fileId=file_id, body=body).execute()
            return True
        except HttpError as e:
            click.echo(f"An error occurred: {e}", err=True)
            return False




