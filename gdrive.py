import os
from datetime import datetime
import click
from googleapiclient.http import MediaIoBaseDownload
from google.auth import default
from googleapiclient.discovery import build


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


def download_file(drive, file, cache_dir):
    file_id = file["id"]
    file_name = file["name"]
    file_details = drive.files().get(fileId=file_id, fields="modifiedTime").execute()
    os.makedirs(cache_dir, exist_ok=True)
    cached_pdf_path = os.path.join(cache_dir, f"{file_id}.pdf")
    if os.path.exists(cached_pdf_path):
        local_creation_time = os.path.getmtime(cached_pdf_path)
        remote_modified_time = file_details.get("modifiedTime")
        remote_modified_timestamp = datetime.fromisoformat(
            remote_modified_time.replace("Z", "+00:00")
        )
        local_creation_datetime = datetime.fromtimestamp(
            local_creation_time
        ).astimezone()
        if remote_modified_timestamp <= local_creation_datetime:
            click.echo(f"Using cached version: {cached_pdf_path}")
            return cached_pdf_path
    request = drive.files().export_media(fileId=file_id, mimeType="application/pdf")
    with open(cached_pdf_path, "wb") as pdf_file:
        downloader = MediaIoBaseDownload(pdf_file, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
    return cached_pdf_path
