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


def download_files(drive, files, cache_dir):
    pdf_paths = []
    for f in files:
        pdf_path = download_file(drive, f, cache_dir)
        pdf_paths.append(pdf_path)
    return pdf_paths


def download_file(drive, file, cache):
    """
    Fetches the PDF export of a Google Doc, using a LocalStorageCache.
    Only re-downloads if remote modifiedTime is newer than the cached file.
    Returns a local filesystem path.
    """
    file_id = file["id"]
    file_name = file["name"]

    # 1) Get the remote modified timestamp
    details = drive.files().get(fileId=file_id, fields="modifiedTime").execute()
    remote_ts = datetime.fromisoformat(details["modifiedTime"].replace("Z", "+00:00"))

    # 2) Attempt cache lookup with freshness check
    #    cache.get expects key (we'll use the file_id as key) and newer_than
    cached_path = cache.get(file_id, newer_than=remote_ts)
    if cached_path:
        click.echo(f"Using cached version: {cached_path}")
        return cached_path

    # 3) Cache miss or stale: export from Drive into memory
    click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
    request = drive.files().export_media(fileId=file_id, mimeType="application/pdf")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    pdf_data = buffer.getvalue()

    # 4) Store into cache and return the new path
    path = cache.put(file_id, pdf_data)
    return path
