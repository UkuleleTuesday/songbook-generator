from typing import Generator, List
from typing import Dict
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload
from google.auth import default
from googleapiclient.discovery import build
import io


def authenticate_drive():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def query_drive_files(drive, source_folder, limit):
    query = f"'{source_folder}' in parents and trashed = false"
    click.echo(f"Executing Drive API query: {query}")
    files = []
    page_token = None
    while True:
        resp = (
            drive.files()
            .list(
                q=query,
                pageSize=limit if limit else 1000,
                fields="nextPageToken, files(id,name)",
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
