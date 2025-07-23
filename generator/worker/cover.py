import click
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import arrow
import fitz  # PyMuPDF
from ..common import config, gdrive, tracing
from .exceptions import CoverGenerationException
from .gcp import get_credentials

DEFAULT_COVER_ID = "1HB1fUAY3uaARoHzSDh2TymfvNBvpKOEE221rubsjKoQ"


class CoverGenerator:
    def __init__(
        self,
        cache,
        drive_service,
        docs_service,
        cover_config: config.Cover,
        enable_templating=True,
    ):
        self.cache = cache
        self.drive = drive_service
        self.docs = docs_service
        self.config = cover_config
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
                f"Hint: make sure that the current authenticated user or service "
                f"account has write permissions to the cover for templating to work."
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
            cover_file_id = self.config.file_id
            if not cover_file_id:
                click.echo("No cover file ID configured. Skipping cover generation.")
                return None

        if self.enable_templating:
            today = arrow.now()
            formatted_date = today.format("Do MMMM YYYY")
            replacement_map = {"{{DATE}}": formatted_date}
            self._apply_template_replacements(cover_file_id, replacement_map)

            try:
                pdf_data = gdrive.download_file(
                    self.drive,
                    cover_file_id,
                    f"Cover-{cover_file_id}",
                    self.cache,
                    "covers",
                    "application/pdf",
                    export=True,
                )
                return fitz.open(stream=pdf_data, filetype="pdf")
            except fitz.EmptyFileError as e:
                raise CoverGenerationException(
                    "Downloaded cover file is corrupted. Please check the file on Google Drive."
                ) from e
            finally:
                # Revert changes
                revert_map = {v: k for k, v in replacement_map.items()}
                self._apply_template_replacements(cover_file_id, revert_map)
        else:
            # No templating, just download the file
            pdf_data = gdrive.download_file(
                self.drive,
                cover_file_id,
                f"Cover-{cover_file_id}",
                self.cache,
                "covers",
                "application/pdf",
                export=False,
            )
            return fitz.open(stream=pdf_data, filetype="pdf")


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
