import os
import click
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient import errors
from google.auth import default
from googleapiclient.discovery import build
from datetime import datetime
import fitz  # PyMuPDF
import toml
from .gdrive import download_file

def load_cover_config():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
        return config.get("cover", {}).get("file-id", None)
    return None


def create_cover_from_template(
    template_cover_id: str,
    replacement_map: dict,
    copy_title: str = None
):
    """
    Copies the original Google Doc, performs text replacements on the copy,
    exports that copy to PDF, and saves it locally.
    
    :param original_doc_id: ID of the source Google Doc
    :param replacement_map: dict mapping placeholder → replacement text
    :param pdf_output_path: local filename for the exported PDF
    :param copy_title: Optional new title for the copied Doc
    """
    # 1) Authenticate
    creds, _ = default(scopes=[
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/drive'
    ])
    docs = build('docs', 'v1', credentials=creds)
    drive = build('drive', 'v3', credentials=creds)

    # 2) Copy the original Doc
    copy_metadata = {'name': copy_title or f'Copy of {template_cover_id}'}
    copy = drive.files().copy(
        fileId=template_cover_id,
        body=copy_metadata
    ).execute()
    copy_id = copy['id']
    print(f"Created copy: {copy_id} (title: {copy.get('name')})")

    # 3) Build batchUpdate requests for all placeholders
    requests = []
    for placeholder, new_text in replacement_map.items():
        requests.append({
            'replaceAllText': {
                'containsText': {
                    'text': placeholder,
                    'matchCase': True
                },
                'replaceText': new_text
            }
        })
    result = docs.documents().batchUpdate(
        documentId=copy_id,
        body={'requests': requests}
    ).execute()
    total = sum(
        reply['replaceAllText']['occurrencesChanged']
        for reply in result.get('replies', [])
        if 'replaceAllText' in reply
    )
    print(f"Replaced {total} occurrences in the copy.")

    return copy_id

def generate_cover(drive, cache_dir):
    cover_file_id = load_cover_config()
    if not cover_file_id:
        click.echo("No cover file ID configured. Skipping cover generation.")
        return


    # Generate the formatted date
    today = datetime.now()
    day = today.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    formatted_date = f"{day}{suffix} {today.strftime('%B %Y')}"

    cover_id = create_cover_from_template(cover_file_id, { "{{DATE}}" : formatted_date })
    pdf_blob = drive.files().export(
        fileId=cover_id,
        mimeType='application/pdf'
    ).execute()

    covers_dir = os.path.join(os.path.expanduser("~/.cache"), "songbook-generator", "cache", "covers")
    os.makedirs(covers_dir, exist_ok=True)
    pdf_output_path = os.path.join(covers_dir, f"{cover_id}.pdf")
    with open(pdf_output_path, 'wb') as f:
        f.write(pdf_blob)
    try:
        cover_pdf = fitz.open(pdf_output_path)
    except fitz.EmptyFileError:
        raise ValueError(f"Downloaded cover file is corrupted: {pdf_output_path}. Please check the file on Google Drive.")
    try:
        drive.files().delete(fileId=cover_id).execute()
        print(f"Deleted copy: {cover_id} from Google Drive.")
    except Exception as e:
        print(f"Failed to delete copy: {cover_id}. Error: {e}")
    return cover_pdf
