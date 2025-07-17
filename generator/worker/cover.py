import click
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import arrow
import fitz  # PyMuPDF
from ..common import config, gdrive
from .exceptions import CoverGenerationException
from .gcp import get_credentials

DEFAULT_COVER_ID = "1HB1fUAY3uaARoHzSDh2TymfvNBvpKOEE221rubsjKoQ"


class CoverGenerator:
    def __init__(self, cache, drive_service, docs_service, enable_templating=True):
        self.cache = cache
        self.drive = drive_service
        self.docs = docs_service
        self.enable_templating = enable_templating

    def _apply_template_replacements(self, document_id: str, replacement_map: dict):
        """
        Applies text replacements to a Google Doc.
        If it fails, it logs an error and continues gracefully.
        """
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

        try:
            result = (
                self.docs.documents()
                .batchUpdate(documentId=document_id, body={"requests": requests})
                .execute()
            )
        except HttpError as e:
            click.echo(
                f"Warning: Could not apply template to cover '{document_id}'. "
                f"This may be due to permissions. Proceeding without templating. "
                f"Error: {e}",
                err=True,
            )
            return
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

    def generate_cover(self, cover_file_id=None):
        if not cover_file_id:
            cover_file_id = config.load_cover_config()
            if not cover_file_id:
                click.echo("No cover file ID configured. Skipping cover generation.")
                return None

        if self.enable_templating:
            today = arrow.now()
            formatted_date = today.format("Do MMMM YYYY")
            self._apply_template_replacements(
                cover_file_id, {"{{DATE}}": formatted_date}
            )

        try:
            pdf_data = gdrive.download_file(
                self.drive,
                cover_file_id,
                f"Cover-{cover_file_id}",
                self.cache,
                "covers",
                "application/pdf",
                # Export when templating, otherwise direct download
                export=self.enable_templating,
            )
            cover_pdf = fitz.open(stream=pdf_data, filetype="pdf")
        except fitz.EmptyFileError as e:
            raise CoverGenerationException(
                "Downloaded cover file is corrupted. Please check the file on Google Drive."
            ) from e
        return cover_pdf


def generate_cover(cache, cover_file_id=None):
    creds = get_credentials(
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    docs_write = build("docs", "v1", credentials=creds)
    drive_write = build("drive", "v3", credentials=creds)
    generator = CoverGenerator(cache, drive_write, docs_write)
    return generator.generate_cover(cover_file_id)
