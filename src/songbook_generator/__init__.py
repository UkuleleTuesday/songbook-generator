import click
import os
import tempfile
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import fitz  # PyMuPDF


@click.command()
@click.option(
    '--source-folder', '-s',
    required=True,
    help='Drive folder ID to read files from'
)
@click.option(
    '--dest-folder', '-d',
    required=True,
    help='Drive folder ID to write output to (not used yet)'
)
@click.option(
    '--limit', '-l',
    type=int,
    default=100,
    help='Limit the number of files to process (default is 100)'
)
def main(source_folder: str, dest_folder: str, limit: int):
    """
    MVP: list files in SOURCE_FOLDER. DEST_FOLDER is reserved for the merged PDF.
    """
    # 1) Authenticate with ADC
    creds, _ = default(
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    drive = build('drive', 'v3', credentials=creds)

    # 2) Query files in the source folder
    query = f"'{source_folder}' in parents and trashed = false"
    click.echo(f"Executing Drive API query: {query}")
    resp = drive.files().list(
        q=query,
        pageSize=limit,  # Use the limit from CLI argument
        fields="files(id,name)",
        orderBy="name_natural"
    ).execute()

    files = resp.get('files', [])
    click.echo(f"Fetched {len(files)} files from Drive. Inspecting response...")
    for f in files:
        click.echo(f"File: {f.get('name')}, ID: {f.get('id')}")
    files = sorted(files, key=lambda f: f['name'])[:limit]
    if not files:
        click.echo(f'No files found in folder {source_folder}.')
        return

    click.echo(f"Starting download of {len(files)} files from folder {source_folder}...")
    temp_dir = tempfile.mkdtemp()
    pdf_paths = []
    cache_dir = os.path.join(temp_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    for f in files:
        file_id = f['id']
        file_name = f['name']
        # Fetch file details to get the md5Checksum
        file_details = drive.files().get(fileId=file_id, fields='modifiedTime').execute()
        print(f"Raw file details: {file_details}")
        file_checksum = file_details.get('modifiedTime')
        print(f"checksum = {file_checksum}")
        cached_pdf_path = os.path.join(cache_dir, f"{file_name}.pdf")
        # Check if the file is already cached and unchanged
        if os.path.exists(cached_pdf_path):
            local_creation_time = os.path.getctime(cached_pdf_path)
            remote_modified_time = file_details.get('modifiedTime')
            remote_modified_timestamp = fitz.get_time(remote_modified_time)
            if remote_modified_timestamp <= local_creation_time:
                click.echo(f"File unchanged, using cached version: {cached_pdf_path}")
                pdf_paths.append(cached_pdf_path)
                continue

        # Download the file if not cached or changed
        click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
        request = drive.files().export_media(fileId=file_id, mimeType='application/pdf')
        with open(cached_pdf_path, 'wb') as pdf_file:
            downloader = MediaIoBaseDownload(pdf_file, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        click.echo(f"Saved PDF: {cached_pdf_path}")

        # Save the checksum for future comparisons if it exists
        if file_checksum:
            cached_checksum_path = os.path.join(cache_dir, f"{file_name}.md5")
            with open(cached_checksum_path, 'w') as checksum_file:
                checksum_file.write(file_checksum)
        else:
            click.echo(f"Checksum missing for file: {file_name}. Skipping caching.")

        pdf_paths.append(cached_pdf_path)

    # 4) Merge all PDFs into a single master PDF
    master_pdf_path = os.path.join(temp_dir, "master.pdf")
    click.echo("Merging all downloaded PDFs into a single master PDF...")
    merged_pdf = fitz.open()
    for pdf_path in pdf_paths:
        pdf_document = fitz.open(pdf_path)
        merged_pdf.insert_pdf(pdf_document)

    click.echo("Adding page numbers to the top-right corner...")
    for page_number in range(len(merged_pdf)):
        click.echo(f"Processing page {page_number + 1}...")
        page = merged_pdf[page_number]
        text = str(page_number + 1)
        x = page.rect.width - 50  # Adjust x-coordinate for top-right corner
        y = 30  # Adjust y-coordinate for top-right corner
        page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))
        intermediate_pdf_path = os.path.join(temp_dir, f"intermediate_page_{page_number + 1}.pdf")
        merged_pdf.save(intermediate_pdf_path)
        click.echo(f"Intermediate PDF saved for page {page_number + 1}: {intermediate_pdf_path}")

    # Create a table of contents page
    click.echo("Creating table of contents...")
    toc_page = merged_pdf.new_page(0)  # Add a new page at the beginning
    toc_text = "Table of Contents\n\n"
    toc_entries = []
    for page_number, file_name in enumerate([os.path.basename(path) for path in pdf_paths], start=1):
        toc_text += f"{page_number}. {file_name}\n"
        toc_entries.append([1, file_name, page_number + 1])
    toc_page.insert_text((50, 50), toc_text, fontsize=12, color=(0, 0, 0))

    # Set the table of contents using set_toc
    merged_pdf.set_toc(toc_entries)

    # Save the final PDF with the table of contents
    merged_pdf.save(master_pdf_path)

    # 5) Output the path to the saved master PDF
    click.echo(f"Master PDF successfully saved at: {master_pdf_path}")

    # Open the generated PDF
    click.echo("Opening the master PDF...")
    os.system(f"xdg-open {master_pdf_path}")

if __name__ == '__main__':
    main()
