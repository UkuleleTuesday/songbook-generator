import os
import click
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient import errors
from datetime import datetime
import fitz  # PyMuPDF
import toml

def load_cover_config():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
        return config.get("cover", {}).get("file-id", None)
    return None

def generate_cover(drive, cache_dir, merged_pdf):
    cover_file_id = load_cover_config()
    if not cover_file_id:
        click.echo("No cover file ID configured. Skipping cover generation.")
        return

    cover_dir = os.path.join(cache_dir, "cover")
    os.makedirs(cover_dir, exist_ok=True)
    cached_cover_path = os.path.join(cover_dir, f"{cover_file_id}.pdf")

    if os.path.exists(cached_cover_path):
        try:
            local_creation_time = os.path.getmtime(cached_cover_path)
            remote_modified_time = drive.files().get(fileId=cover_file_id, fields='modifiedTime').execute().get('modifiedTime')
            remote_modified_timestamp = datetime.fromisoformat(remote_modified_time.replace("Z", "+00:00"))
            local_creation_datetime = datetime.fromtimestamp(local_creation_time).astimezone()
            if remote_modified_timestamp <= local_creation_datetime:
                click.echo(f"Using cached cover: {cached_cover_path}")
                if os.path.getsize(cached_cover_path) == 0:
                    raise ValueError(f"Downloaded cover file is empty: {cached_cover_path}. Please check the file on Google Drive.")
                try:
                    cover_pdf = fitz.open(cached_cover_path)
                except fitz.EmptyFileError:
                    raise ValueError(f"Downloaded cover file is corrupted: {cached_cover_path}. Please check the file on Google Drive.")
                merged_pdf.insert_pdf(cover_pdf, 0)
                return
        except fitz.EmptyFileError:
            click.echo(f"Cached cover file is empty or corrupted: {cached_cover_path}. Redownloading...")

    try:
        request = drive.files().get_media(fileId=cover_file_id)
    except errors.HttpError as e:
        if "fileNotExportable" in str(e):
            raise ValueError(f"Cover file (ID: {cover_file_id}) is not exportable. Ensure it is a valid file type.")
        raise
    with open(cached_cover_path, 'wb') as cover_file:
        downloader = MediaIoBaseDownload(cover_file, request)
        done = False
        try:
            while not done:
                _, done = downloader.next_chunk()
        except errors.HttpError as e:
            if "fileNotExportable" in str(e):
                raise ValueError(f"Cover file (ID: {cover_file_id}) is not exportable. Ensure it is a valid Docs Editors file.")
    click.echo(f"Downloading cover file (ID: {cover_file_id})...")
    cover_pdf = fitz.open(cached_cover_path)
    merged_pdf.insert_pdf(cover_pdf, 0)
