import click
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import arrow
import fitz  # PyMuPDF
from ..common import config, gdrive
from .exceptions import CoverGenerationException
from .gcp import get_credentials

DEFAULT_COVER_ID = "1HB1fUAY3uaARoHzSDh2TymfvNBvpKOEE221rubsjKoQ"


def create_cover_from_template(
    drive,
    docs,
    template_cover_id: str,
    replacement_map: dict,
    copy_title: str = None,
):
    """
    Copies the original Google Doc, performs text replacements on the copy,
    exports that copy to PDF, and saves it locally.

    :param drive: Authenticated Google Drive service object.
    :param docs: Authenticated Google Docs service object.
    :param original_doc_id: ID of the source Google Doc
    :param replacement_map: dict mapping placeholder → replacement text
    :param pdf_output_path: local filename for the exported PDF
    :param copy_title: Optional new title for the copied Doc
    """
    # 1) Copy the original Doc. Place it in root of My Drive to avoid
    # permission issues with the source folder.
    root_folder_id = drive.files().get(fileId="root", fields="id").execute()["id"]
    copy_metadata = {
        "name": copy_title or f"Copy of {template_cover_id}",
        "parents": [root_folder_id],
    }
    copy = drive.files().copy(fileId=template_cover_id, body=copy_metadata).execute()
    copy_id = copy["id"]
    click.echo(f"Created copy: {copy_id} (title: {copy.get('name')})")

    # 3) Build batchUpdate requests for all placeholders
    requests = []
    for placeholder, new_text in replacement_map.items():
        requests.append(
            {
                "replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": new_text,
                }
            }
        )
    result = (
        docs.documents()
        .batchUpdate(documentId=copy_id, body={"requests": requests})
        .execute()
    )
    total = 0
    for reply in result.get("replies", []):
        if reply is None:
            continue
        try:
            replace_all_text = reply.get("replaceAllText")
            if replace_all_text is not None and isinstance(replace_all_text, dict):
                occurrences = replace_all_text.get("occurrencesChanged")
                if isinstance(occurrences, int):
                    total += occurrences
        except (KeyError, TypeError, AttributeError):
            # Skip replies that have malformed structure
            pass
    click.echo(f"Replaced {total} occurrences in the copy.")

    return copy_id


def generate_cover(cache, cover_file_id=None):
    if not cover_file_id:
        cover_file_id = config.load_cover_config()
        if not cover_file_id:
            click.echo("No cover file ID configured. Skipping cover generation.")
            return None

    creds = get_credentials(
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    docs_write = build("docs", "v1", credentials=creds)
    drive_write = build("drive", "v3", credentials=creds)

    today = arrow.now()
    formatted_date = today.format("Do MMMM YYYY")

    copy_id = create_cover_from_template(
        drive_write, docs_write, cover_file_id, {"{{DATE}}": formatted_date}
    )

    try:
        pdf_data = gdrive.download_file(
            drive_write,
            copy_id,
            f"Cover-{copy_id}",
            cache,
            "covers",
            "application/pdf",
        )
        cover_pdf = fitz.open(stream=pdf_data, filetype="pdf")
    except fitz.EmptyFileError as e:
        raise CoverGenerationException(
            "Downloaded cover file is corrupted. Please check the file on Google Drive."
        ) from e
    finally:
        try:
            drive_write.files().delete(fileId=copy_id).execute()
            click.echo(f"Deleted copy: {copy_id} from Google Drive.")
        except HttpError as e:
            raise CoverGenerationException(
                f"Failed to delete temporary cover file {copy_id} from Google Drive. "
                f"It may need to be manually removed. Original error: {e}"
            ) from e
    return cover_pdf
