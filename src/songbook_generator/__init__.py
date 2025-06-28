import click
import os
import tempfile
from datetime import datetime
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import fitz  # PyMuPDF
import toml


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


def download_files(drive, files, cache_dir):
    pdf_paths = []
    for f in files:
        file_id = f['id']
        file_name = f['name']
        file_details = drive.files().get(fileId=file_id, fields='modifiedTime').execute()
        cached_pdf_path = os.path.join(cache_dir, f"{file_id}.pdf")
        if os.path.exists(cached_pdf_path):
            local_creation_time = os.path.getmtime(cached_pdf_path)
            remote_modified_time = file_details.get('modifiedTime')
            remote_modified_timestamp = datetime.fromisoformat(remote_modified_time.replace("Z", "+00:00"))
            local_creation_datetime = datetime.fromtimestamp(local_creation_time).astimezone()
            if remote_modified_timestamp <= local_creation_datetime:
                click.echo(f"Using cached version: {cached_pdf_path}")
                pdf_paths.append(cached_pdf_path)
                continue
        request = drive.files().export_media(fileId=file_id, mimeType='application/pdf')
        with open(cached_pdf_path, 'wb') as pdf_file:
            downloader = MediaIoBaseDownload(pdf_file, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
        pdf_paths.append(cached_pdf_path)
    return pdf_paths


def merge_pdfs(pdf_paths, files, cache_dir):
    master_pdf_path = os.path.join(cache_dir, "master.pdf")
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
    def build_table_of_contents(merged_pdf, files):
        toc_page = merged_pdf.new_page(0)
        toc_text = "Table of Contents\n\n"
        toc_entries = []
        column_width = 250  # Width of each column
        column_spacing = 20  # Space between columns
        column_height = toc_page.rect.height - 100  # Adjust for margins
        current_y = 50
        current_x = 50

        toc_font, toc_fontsize = load_toc_config()

        for page_number, file in enumerate(files, start=1):
            file_name = file['name']
            toc_text_line = f"{page_number}. {file_name}"
            toc_entries.append([1, file_name, page_number + 1])
            try:
                toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=toc_fontsize, fontname=toc_font, color=(0, 0, 0))
            except Exception as e:
                click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
                toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=9, fontname="helv", color=(0, 0, 0))
            current_y += 20  # Line spacing
            if current_y > column_height:  # Move to next column if overspills
                current_y = 50
                current_x += column_width + column_spacing

        try:
            toc_page.insert_text((50, 50), toc_text, fontsize=toc_fontsize, fontname=toc_font, color=(0, 0, 0))
        except Exception as e:
            click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
            toc_page.insert_text((50, 50), toc_text, fontsize=9, fontname="helv", color=(0, 0, 0))
        merged_pdf.set_toc(toc_entries)

    build_table_of_contents(merged_pdf, files)
    toc_page = merged_pdf.new_page(0)
    toc_text = "Table of Contents\n\n"
    toc_entries = []
    column_width = 250  # Width of each column
    column_spacing = 20  # Space between columns
    column_height = toc_page.rect.height - 100  # Adjust for margins
    current_y = 50
    current_x = 50

    # Load configuration for TOC
    def load_toc_config():
        config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
        if os.path.exists(config_path):
            config = toml.load(config_path)
            return config.get("toc", {}).get("font", "helv"), config.get("toc", {}).get("fontsize", 9)
        return "helv", 9

    toc_font, toc_fontsize = load_toc_config()

    for page_number, file in enumerate(files, start=1):
        file_name = file['name']
        toc_text_line = f"{page_number}. {file_name}"
        toc_entries.append([1, file_name, page_number + 1])
        try:
            toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=toc_fontsize, fontname=toc_font, color=(0, 0, 0))
        except Exception as e:
            click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
            toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=9, fontname="helv", color=(0, 0, 0))
        current_y += 20  # Line spacing
        if current_y > column_height:  # Move to next column if overspills
            current_y = 50
            current_x += column_width + column_spacing

    try:
        toc_page.insert_text((50, 50), toc_text, fontsize=toc_fontsize, fontname=toc_font, color=(0, 0, 0))
    except Exception as e:
        click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
        toc_page.insert_text((50, 50), toc_text, fontsize=9, fontname="helv", color=(0, 0, 0))
    merged_pdf.set_toc(toc_entries)
    merged_pdf.save(master_pdf_path)
    return master_pdf_path


@click.command()
@click.option('--source-folder', '-s', required=True, help='Drive folder ID to read files from')
@click.option('--limit', '-l', type=int, default=None, help='Limit the number of files to process (no limit by default)')
def main(source_folder: str, limit: int):
    drive = authenticate_drive()
    click.echo("Authenticating with Google Drive...")
    files = query_drive_files(drive, source_folder, limit)
    if not files:
        click.echo(f'No files found in folder {source_folder}.')
        return
    cache_dir = os.path.join(os.path.expanduser("~/.cache"), "songbook-generator", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    click.echo(f"Found {len(files)} files in the source folder. Starting download...")
    pdf_paths = download_files(drive, files, cache_dir)
    click.echo("Merging downloaded PDFs into a single master PDF...")
    master_pdf_path = merge_pdfs(pdf_paths, files, cache_dir)
    click.echo(f"Master PDF successfully saved at: {master_pdf_path}")
    click.echo("Opening the master PDF...")
    os.system(f"xdg-open {master_pdf_path}")

if __name__ == '__main__':
    main()
def load_toc_config():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
        return config.get("toc", {}).get("font", "helv"), config.get("toc", {}).get("fontsize", 9)
    return "helv", 9


def build_table_of_contents(merged_pdf, files):
    toc_page = merged_pdf.new_page(0)
    toc_text = "Table of Contents\n\n"
    toc_entries = []
    column_width = 250  # Width of each column
    column_spacing = 20  # Space between columns
    column_height = toc_page.rect.height - 100  # Adjust for margins
    current_y = 50
    current_x = 50

    toc_font, toc_fontsize = load_toc_config()

    for page_number, file in enumerate(files, start=1):
        file_name = file['name']
        toc_text_line = f"{page_number}. {file_name}"
        toc_entries.append([1, file_name, page_number + 1])
        try:
            toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=toc_fontsize, fontname=toc_font, color=(0, 0, 0))
        except Exception as e:
            click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
            toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=9, fontname="helv", color=(0, 0, 0))
        current_y += 20  # Line spacing
        if current_y > column_height:  # Move to next column if overspills
            current_y = 50
            current_x += column_width + column_spacing

    try:
        toc_page.insert_text((50, 50), toc_text, fontsize=toc_fontsize, fontname=toc_font, color=(0, 0, 0))
    except Exception as e:
        click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
        toc_page.insert_text((50, 50), toc_text, fontsize=9, fontname="helv", color=(0, 0, 0))
    merged_pdf.set_toc(toc_entries)
