import click
import os
import tempfile
from datetime import datetime
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import fitz  # PyMuPDF

import toml
from .gdrive import download_files
from . import toc, cover

DEFAULT_GDRIVE_FOLDER_ID = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"

def load_config_folder_ids():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
        folder_ids = config.get("song-sheets", {}).get("folder-ids", [DEFAULT_GDRIVE_FOLDER_ID])
        return folder_ids if isinstance(folder_ids, list) else [folder_ids]
    return DEFAULT_GDRIVE_FOLDER_ID


def authenticate_drive():
    creds, _ = default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
    return build('drive', 'v3', credentials=creds)


def query_drive_files(drive, source_folder, limit):
    query = f"'{source_folder}' in parents and trashed = false"
    click.echo(f"Executing Drive API query: {query}")
    files = []
    page_token = None
    while True:
        resp = drive.files().list(
            q=query,
            pageSize=limit if limit else 1000,
            fields="nextPageToken, files(id,name)",
            orderBy="name_natural",
            pageToken=page_token
        ).execute()
        files.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token or (limit and len(files) >= limit):
            break
    return files[:limit] if limit else files



def merge_pdfs(pdf_paths, files, cache_dir, drive):
    merged_pdf = fitz.open()

    for pdf_path in pdf_paths:
        pdf_document = fitz.open(pdf_path)
        merged_pdf.insert_pdf(pdf_document)
    for page_number in range(len(merged_pdf)):
        page = merged_pdf[page_number]
        text = str(page_number + 1)
        x = page.rect.width - 50
        y = 30
        page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))

    return merged_pdf


@click.command()
@click.option('--source-folder', '-s', multiple=True, default=load_config_folder_ids(), help='Drive folder IDs to read files from (can be passed multiple times)')
@click.option('--limit', '-l', type=int, default=None, help='Limit the number of files to process (no limit by default)')
def main(source_folder: str, limit: int):
    drive = authenticate_drive()
    click.echo("Authenticating with Google Drive...")
    files = []
    for folder in source_folder:
        files.extend(query_drive_files(drive, folder, limit))
    if not files:
        click.echo(f'No files found in folder {source_folder}.')
        return
    cache_dir = os.path.join(os.path.expanduser("~/.cache"), "songbook-generator", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    click.echo(f"Found {len(files)} files in the source folder. Starting download...")
    song_sheets_dir = os.path.join(cache_dir, "song-sheets")
    os.makedirs(song_sheets_dir, exist_ok=True)
    pdf_paths = download_files(drive, files, song_sheets_dir)
    click.echo("Merging downloaded PDFs into a single master PDF...")
    merged_pdf = merge_pdfs(pdf_paths, files, cache_dir, drive)
    toc_pdf = toc.build_table_of_contents(files)
    merged_pdf.insert_pdf(toc_pdf, start_at=0)
    cover_pdf = cover.generate_cover(drive, cache_dir)
    merged_pdf.insert_pdf(cover_pdf, start_at=0)

    try:
        master_pdf_path = os.path.join(cache_dir, "master.pdf")
        merged_pdf.save(master_pdf_path)  # Save the merged PDF
        if not os.path.exists(master_pdf_path):
            raise FileNotFoundError(f"Failed to save master PDF at {master_pdf_path}")
    except Exception as e:
        click.echo(f"Error saving master PDF: {e}")
        return None

    if master_pdf_path and os.path.exists(master_pdf_path):
        click.echo(f"Master PDF successfully saved at: {master_pdf_path}")
        click.echo("Opening the master PDF...")
        os.system(f"xdg-open {master_pdf_path}")
    else:
        click.echo("Failed to save or locate the master PDF.")


if __name__ == '__main__':
    main()
