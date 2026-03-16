from typing import Generator, List, Dict, Optional, Set, Union
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from googleapiclient.errors import HttpError
import io
from loguru import logger
from opentelemetry import trace
from googleapiclient.discovery import build

from .filters import FilterGroup, PropertyFilter
from ..worker.models import File
from .config import get_settings, GoogleDriveClientConfig
from .tracing import get_tracer
from google.auth import credentials

SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"

tracer = get_tracer(__name__)


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
        self,
        cache,
        credentials: Optional[credentials.Credentials] = None,
        drive=None,
        config: Optional[GoogleDriveClientConfig] = None,
    ):
        if drive:
            self.drive = drive
        elif credentials:
            self.drive = client(credentials)
        else:
            raise ValueError("Either 'credentials' or 'drive' must be provided.")
        self.cache = cache
        self.config = config or get_settings().google_cloud.drive_client

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
                .execute(num_retries=self.config.api_retries)
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
        source_folders: List[str],
        property_filters: Optional[Dict[str, str]] = None,
        modified_after: Optional[datetime] = None,
    ) -> List[File]:
        """
        Query Google Drive files with optional property filtering.

        Args:
            source_folders: List of folder IDs to search in
            property_filters: Optional dict of property_name -> value pairs to filter by

        Returns:
            List of files, or empty list if error occurs
        """
        parent_queries = [f"'{folder_id}' in parents" for folder_id in source_folders]
        base_query = f"({' or '.join(parent_queries)}) and trashed = false"
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
                    .execute(num_retries=self.config.api_retries)
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
                        f"Permission denied accessing folder(s) {source_folders}. Check your access rights."
                    )
                elif error_code == 404:
                    click.echo(
                        f"Folder(s) {source_folders} not found. Check the folder ID(s)."
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
        source_folders: List[str],
        client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    ) -> List[File]:
        """
        Query Google Drive files and apply client-side filtering.

        Args:
            source_folders: List of folder IDs to search in
            client_filter: Client-side filter to apply after fetching files

        Returns:
            List of files matching the client-side filter
        """
        # First, get all files from Drive (no server-side property filtering)
        click.echo("Fetching all files from Drive for client-side filtering...")
        all_files = self.query_drive_files(source_folders, None)

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

    def download_file_stream(self, file: File, use_cache: bool = True) -> io.BytesIO:
        """
        Fetches the PDF export of a Google Doc, using a LocalStorageCache.
        Only re-downloads if remote modifiedTime is newer than the cached file.
        Returns a BytesIO stream of the file.
        """
        # Google Docs need to be exported, while regular PDFs can be downloaded directly.
        should_export = file.mimeType == "application/vnd.google-apps.document"

        pdf_data = self.download_file(
            file_id=file.id,
            file_name=file.name,
            cache_prefix="song-sheets",
            mime_type="application/pdf",
            export=should_export,
            use_cache=use_cache,
        )
        return io.BytesIO(pdf_data)

    def stream_file_bytes(
        self, files: List[File], use_cache: bool = True
    ) -> Generator[bytes, None, None]:
        """
        Generator that yields the bytes of each file.
        Files are fetched from cache if available, otherwise downloaded from Drive.
        """
        for f in files:
            with self.download_file_stream(f, use_cache=use_cache) as stream:
                yield stream.getvalue()

    def download_file(
        self,
        file_id: str,
        file_name: str,
        cache_prefix: str,
        mime_type: str = "application/pdf",
        export: bool = True,
        use_cache: bool = True,
    ) -> bytes:
        """
        Generic file downloader with caching.

        Can either download a file directly or export a Google Doc to a specific format.
        """
        span = trace.get_current_span()
        span.set_attribute("cache.enabled", use_cache)
        cache_key = f"{cache_prefix}/{file_id}.pdf"
        span.set_attribute("cache.key", cache_key)

        if use_cache:
            details = (
                self.drive.files()
                .get(fileId=file_id, fields="modifiedTime")
                .execute(num_retries=self.config.api_retries)
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
                    .get(fileId=file_id, fields="id,name,parents,properties,mimeType")
                    .execute(num_retries=self.config.api_retries)
                )
                file_obj = File(
                    id=file_id,
                    name=file_metadata.get("name", f"file_{file_id}"),
                    properties=file_metadata.get("properties", {}),
                    mimeType=file_metadata.get("mimeType"),
                    parents=file_metadata.get("parents", []),
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

    def download_file_bytes(self, file: File, use_cache: bool = True) -> bytes:
        """
        Legacy function for backward compatibility.
        Fetches the PDF export and returns raw bytes.
        """
        with self.download_file_stream(file, use_cache=use_cache) as stream:
            return stream.getvalue()

    def list_folder_contents(
        self,
        folder_id: str,
        resolve_shortcuts: bool = True,
    ) -> List[File]:
        """
        List all files in a Drive folder, resolving shortcuts to their targets.

        Shortcuts to files are always resolved so callers receive the target
        file's ID and MIME type while retaining the shortcut's display name
        (as it appears in the folder) for ordering and categorisation
        purposes.

        When *resolve_shortcuts* is ``True`` (the default), shortcuts that
        point to folders are followed recursively: all files inside the
        target folder are fetched and included in the results.  Cycle
        detection prevents infinite loops caused by circular shortcuts.
        When ``False``, folder shortcuts are skipped.

        Args:
            folder_id: The Google Drive folder ID to list.
            resolve_shortcuts: Whether to recursively follow shortcuts that
                point to folders.  Defaults to ``True``.

        Returns:
            List of File objects.  Shortcuts to files are returned as the
            target file with the shortcut's display name.  When
            *resolve_shortcuts* is ``True``, shortcuts to folders are
            expanded so their contents are included inline.
        """
        return self._list_folder_contents(
            folder_id,
            visited_folder_ids=set(),
            resolve_shortcuts=resolve_shortcuts,
        )

    def _list_folder_contents(
        self,
        folder_id: str,
        visited_folder_ids: Set[str],
        resolve_shortcuts: bool,
    ) -> List[File]:
        """
        Internal implementation of list_folder_contents with cycle tracking.

        Args:
            folder_id: The Google Drive folder ID to list.
            visited_folder_ids: Set of folder IDs already visited in this
                traversal, used to detect and break cycles.
            resolve_shortcuts: Whether to recursively follow folder shortcuts.

        Returns:
            List of File objects with shortcuts resolved.
        """
        folder_mime = "application/vnd.google-apps.folder"
        # Exclude sub-folders so they are never treated as song files.
        query = (
            f"'{folder_id}' in parents"
            f" and trashed = false"
            f" and mimeType != '{folder_mime}'"
        )
        files = []
        page_token = None

        visited_folder_ids.add(folder_id)

        while True:
            try:
                resp = (
                    self.drive.files()
                    .list(
                        q=query,
                        pageSize=1000,
                        fields=(
                            "nextPageToken, "
                            "files(id,name,mimeType,parents,properties,"
                            "shortcutDetails)"
                        ),
                        orderBy="name",
                        pageToken=page_token,
                    )
                    .execute(num_retries=self.config.api_retries)
                )
            except HttpError as e:
                error_code = e.resp.status if e.resp else "unknown"
                click.echo(
                    f"Error listing folder {folder_id} (HTTP {error_code}): {e}",
                    err=True,
                )
                break

            for f in resp.get("files", []):
                if f.get("mimeType") == SHORTCUT_MIME_TYPE:
                    shortcut_details = f.get("shortcutDetails") or {}
                    target_id = shortcut_details.get("targetId")
                    target_mime = shortcut_details.get("targetMimeType")
                    if not target_id:
                        click.echo(
                            f"Warning: shortcut '{f['name']}' has no "
                            "target ID, skipping.",
                            err=True,
                        )
                        continue
                    if target_mime == folder_mime:
                        if not resolve_shortcuts:
                            continue
                        if target_id in visited_folder_ids:
                            click.echo(
                                f"Warning: shortcut '{f['name']}' points to "
                                f"folder {target_id} which was already "
                                "visited, skipping to prevent infinite "
                                "recursion.",
                                err=True,
                            )
                            continue
                        # Recursively include all files in the target folder.
                        files.extend(
                            self._list_folder_contents(
                                target_id,
                                visited_folder_ids=visited_folder_ids,
                                resolve_shortcuts=resolve_shortcuts,
                            )
                        )
                        continue
                    files.append(
                        File(
                            id=target_id,
                            name=f["name"],
                            mimeType=target_mime,
                            properties=f.get("properties") or {},
                            parents=f.get("parents") or [],
                        )
                    )
                else:
                    files.append(
                        File(
                            id=f["id"],
                            name=f["name"],
                            mimeType=f.get("mimeType"),
                            properties=f.get("properties") or {},
                            parents=f.get("parents") or [],
                        )
                    )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return files

    def find_file_in_folder(self, folder_id: str, filename: str) -> Optional[File]:
        """
        Find a file by exact name in a Drive folder.

        Args:
            folder_id: The Google Drive folder ID to search in.
            filename: The exact file name to look for.

        Returns:
            The matching File object, or None if not found.
        """
        escaped_name = filename.replace("'", "\\'")
        query = (
            f"'{folder_id}' in parents and name = '{escaped_name}' and trashed = false"
        )
        try:
            resp = (
                self.drive.files()
                .list(
                    q=query,
                    pageSize=1,
                    fields="files(id,name,mimeType,parents,properties)",
                )
                .execute(num_retries=self.config.api_retries)
            )
            files = resp.get("files", [])
            if not files:
                return None
            f = files[0]
            return File(
                id=f["id"],
                name=f["name"],
                mimeType=f.get("mimeType"),
                properties=f.get("properties") or {},
                parents=f.get("parents") or [],
            )
        except HttpError as e:
            click.echo(
                f"Error searching for '{filename}' in folder {folder_id}: {e}",
                err=True,
            )
            return None

    def find_subfolder_by_name(self, parent_folder_id: str, name: str) -> Optional[str]:
        """
        Find a direct child subfolder by name (case-insensitive) in a Drive folder.

        All direct child folders of *parent_folder_id* are fetched and the
        first one whose name matches *name* (case-insensitively) is returned.

        Args:
            parent_folder_id: The Drive folder ID to search within.
            name: The subfolder name to look for (case-insensitive).

        Returns:
            The Drive folder ID of the matching subfolder, or ``None`` if not
            found or an error occurs.
        """
        folder_mime = "application/vnd.google-apps.folder"
        query = (
            f"'{parent_folder_id}' in parents"
            f" and mimeType = '{folder_mime}'"
            f" and trashed = false"
        )
        try:
            resp = (
                self.drive.files()
                .list(
                    q=query,
                    pageSize=100,
                    fields="files(id,name)",
                    orderBy="name",
                )
                .execute(num_retries=self.config.api_retries)
            )
        except HttpError as e:
            error_code = e.resp.status if e.resp else "unknown"
            click.echo(
                f"Error listing subfolders of {parent_folder_id} "
                f"(HTTP {error_code}): {e}",
                err=True,
            )
            return None

        target = name.lower()
        for f in resp.get("files", []):
            if f["name"].lower() == target:
                return f["id"]
        return None

    def find_all_files_named(
        self,
        filename: str,
        source_folders: Optional[List[str]] = None,
    ) -> List[File]:
        """
        Find all files with the given exact name across accessible Drive.

        Args:
            filename: The exact file name to search for.
            source_folders: Optional list of folder IDs to restrict the
                search to direct children of those folders.  When ``None``
                or empty the search is performed across all Drive files
                accessible to the current credentials.

        Returns:
            List of matching File objects (may be empty).
        """
        with tracer.start_as_current_span("find_all_files_named") as span:
            span.set_attribute("gdrive.query_filename", filename)
            span.set_attribute(
                "gdrive.source_folders_count",
                len(source_folders) if source_folders else 0,
            )
            span.set_attribute("gdrive.search_scoped", bool(source_folders))

            escaped_name = filename.replace("'", "\\'")
            query = f"name = '{escaped_name}' and trashed = false"
            if source_folders:
                parent_queries = [f"'{fid}' in parents" for fid in source_folders]
                query += f" and ({' or '.join(parent_queries)})"

            files: List[File] = []
            page_token = None
            pages_fetched = 0

            while True:
                try:
                    resp = (
                        self.drive.files()
                        .list(
                            q=query,
                            pageSize=100,
                            fields=(
                                "nextPageToken, "
                                "files(id,name,mimeType,parents,properties)"
                            ),
                            pageToken=page_token,
                        )
                        .execute(num_retries=self.config.api_retries)
                    )
                except HttpError as e:
                    error_code = e.resp.status if e.resp else "unknown"
                    logger.error(
                        f"Drive API error searching for {filename!r} "
                        f"(HTTP {error_code}): {e}"
                    )
                    click.echo(
                        f"Error searching for '{filename}' (HTTP {error_code}): {e}",
                        err=True,
                    )
                    span.set_attribute("gdrive.error_code", str(error_code))
                    span.set_attribute("gdrive.error", str(e))
                    break

                pages_fetched += 1
                page_results = resp.get("files", [])
                for f in page_results:
                    files.append(
                        File(
                            id=f["id"],
                            name=f["name"],
                            mimeType=f.get("mimeType"),
                            properties=f.get("properties") or {},
                            parents=f.get("parents") or [],
                        )
                    )

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            span.set_attribute("gdrive.files_found", len(files))
            span.set_attribute("gdrive.pages_fetched", pages_fetched)
            return files

    def download_raw_bytes(self, file_id: str) -> bytes:
        """
        Download the raw content of a Drive file without caching or
        PDF export.

        Args:
            file_id: The Google Drive file ID to download.

        Returns:
            Raw file content as bytes.
        """
        request = self.drive.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

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
                self.drive.files()
                .get(fileId=file_id, fields="properties")
                .execute(num_retries=self.config.api_retries)
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
                self.drive.files()
                .get(fileId=file_id, fields="properties")
                .execute(num_retries=self.config.api_retries)
            )
            properties = file_metadata.get("properties", {})
            properties[key] = value

            body = {"properties": properties}
            self.drive.files().update(fileId=file_id, body=body).execute(
                num_retries=self.config.api_retries
            )
            return True
        except HttpError as e:
            click.echo(f"An error occurred: {e}", err=True)
            return False

    def create_folder(self, name: str, parent_id: str) -> str:
        """
        Create a new folder in Google Drive.

        Args:
            name: The name of the new folder.
            parent_id: The ID of the parent folder.

        Returns:
            The ID of the newly created folder.
        """
        with tracer.start_as_current_span("create_folder") as span:
            span.set_attribute("folder.name", name)
            span.set_attribute("folder.parent_id", parent_id)
            body = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            result = (
                self.drive.files()
                .create(body=body, fields="id")
                .execute(num_retries=self.config.api_retries)
            )
            folder_id = result["id"]
            span.set_attribute("folder.id", folder_id)
            logger.info(
                f"create_folder: created folder {name!r} "
                f"(id={folder_id!r}) in parent {parent_id!r}"
            )
            return folder_id

    def upload_file_bytes(
        self,
        name: str,
        content: bytes,
        parent_id: str,
        mime_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload bytes as a new file to Google Drive.

        Args:
            name: The name of the new file.
            content: The file content as bytes.
            parent_id: The ID of the parent folder.
            mime_type: The MIME type of the file.

        Returns:
            The ID of the newly uploaded file.
        """
        with tracer.start_as_current_span("upload_file_bytes") as span:
            span.set_attribute("file.name", name)
            span.set_attribute("file.parent_id", parent_id)
            span.set_attribute("file.mime_type", mime_type)
            body = {
                "name": name,
                "parents": [parent_id],
            }
            media = MediaIoBaseUpload(
                io.BytesIO(content),
                mimetype=mime_type,
                resumable=False,
            )
            result = (
                self.drive.files()
                .create(body=body, media_body=media, fields="id")
                .execute(num_retries=self.config.api_retries)
            )
            file_id = result["id"]
            span.set_attribute("file.id", file_id)
            logger.info(
                f"upload_file_bytes: uploaded {name!r} (id={file_id!r}) "
                f"to parent {parent_id!r}"
            )
            return file_id

    def create_shortcut(self, name: str, target_id: str, parent_id: str) -> str:
        """
        Create a Drive shortcut pointing to an existing file.

        Args:
            name: The name of the shortcut.
            target_id: The Google Drive file ID of the shortcut target.
            parent_id: The ID of the parent folder for the shortcut.

        Returns:
            The ID of the newly created shortcut.
        """
        with tracer.start_as_current_span("create_shortcut") as span:
            span.set_attribute("shortcut.name", name)
            span.set_attribute("shortcut.target_id", target_id)
            span.set_attribute("shortcut.parent_id", parent_id)
            body = {
                "name": name,
                "mimeType": SHORTCUT_MIME_TYPE,
                "parents": [parent_id],
                "shortcutDetails": {"targetId": target_id},
            }
            result = (
                self.drive.files()
                .create(body=body, fields="id")
                .execute(num_retries=self.config.api_retries)
            )
            shortcut_id = result["id"]
            span.set_attribute("shortcut.id", shortcut_id)
            logger.info(
                f"create_shortcut: created shortcut {name!r} → "
                f"{target_id!r} (id={shortcut_id!r}) in parent "
                f"{parent_id!r}"
            )
            return shortcut_id
