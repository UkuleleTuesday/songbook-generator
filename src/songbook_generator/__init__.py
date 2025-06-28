import click
import os
import tempfile
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pypdf import PdfWriter


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
    resp = drive.files().list(
        q=query,
        pageSize=1000,  # Fetch a large number of files to ensure all are retrieved
        fields="files(id,name)"
    ).execute()

    files = sorted(resp.get('files', []), key=lambda f: f['name'])[:limit]
    if not files:
        click.echo(f'No files found in folder {source_folder}.')
        return

    click.echo(f"Starting download of {len(files)} files from folder {source_folder}...")
    temp_dir = tempfile.mkdtemp()
    pdf_paths = []
    for f in files:
        file_id = f['id']
        file_name = f['name']
        pdf_path = os.path.join(temp_dir, f"{file_name}.pdf")
        click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
        request = drive.files().export_media(fileId=file_id, mimeType='application/pdf')
        with open(pdf_path, 'wb') as pdf_file:
            downloader = MediaIoBaseDownload(pdf_file, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        click.echo(f"Saved PDF: {pdf_path}")
        pdf_paths.append(pdf_path)

    # 4) Merge all PDFs into a single master PDF
    master_pdf_path = os.path.join(temp_dir, "master.pdf")
    click.echo("Merging all downloaded PDFs into a single master PDF...")
    writer = PdfWriter()
    for pdf_path in pdf_paths:
        writer.append(pdf_path)

    # Add page numbers to the top-right corner
    for page_number, page in enumerate(writer.pages, start=1):
        page.add_text(
            text=str(page_number),
            x=500,  # Adjust x-coordinate for top-right corner
            y=750,  # Adjust y-coordinate for top-right corner
            size=12  # Font size
        )
    with open(master_pdf_path, "wb") as master_pdf_file:
        writer.write(master_pdf_file)

    # 5) Output the path to the saved master PDF
    click.echo(f"Master PDF successfully saved at: {master_pdf_path}")

if __name__ == '__main__':
    main()
