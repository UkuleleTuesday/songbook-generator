import click
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import arrow
import fitz  # PyMuPDF
from ..common import config
from ..common.gdrive import GoogleDriveClient
from .exceptions import CoverGenerationException
from .gcp import get_credentials


def _next_tuesday(when):
    """Date of the upcoming Tuesday, or `when` itself if it is already a Tuesday.

    This lets a cover be generated ahead of a session while still showing the
    coming Tuesday's date.
    """
    # arrow/datetime weekday(): Monday=0, Tuesday=1, ... Sunday=6.
    # Python's modulo keeps the shift non-negative: Mon=+1, Tue=+0, Wed=+6, Sun=+2.
    return when.shift(days=(1 - when.weekday()) % 7)


class CoverGenerator:
    def __init__(
        self,
        gdrive_client: GoogleDriveClient,
        docs_service,
        cover_config: config.Cover,
        enable_templating=True,
    ):
        self.gdrive_client = gdrive_client
        self.docs = docs_service
        self.config = cover_config
        self.enable_templating = enable_templating

    def _apply_template_replacements(self, document_id: str, replacement_map: dict):
        """
        Applies text replacements to a Google Doc.

        Returns a mapping of each placeholder to the number of occurrences that
        were replaced (0 when the placeholder is absent). If the update fails, it
        logs an error, continues gracefully, and returns an empty mapping.
        """
        placeholders = list(replacement_map.keys())
        requests = [
            {
                "replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": replacement_map[placeholder],
                }
            }
            for placeholder in placeholders
        ]

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
            return {}

        # Replies are returned in the same order as the requests we sent.
        replies = result.get("replies", []) if isinstance(result, dict) else []
        counts = {placeholder: 0 for placeholder in placeholders}
        for placeholder, reply in zip(placeholders, replies):
            if not isinstance(reply, dict):
                continue
            replace_all_text = reply.get("replaceAllText")
            if isinstance(replace_all_text, dict):
                occurrences = replace_all_text.get("occurrencesChanged")
                if isinstance(occurrences, int):
                    counts[placeholder] = occurrences
        click.echo(f"Replaced {sum(counts.values())} occurrences in the copy.")
        return counts

    def generate_cover(self, cover_file_id=None):
        if not cover_file_id:
            cover_file_id = self.config.file_id
            if not cover_file_id:
                click.echo("No cover file ID configured. Skipping cover generation.")
                return None

        if self.enable_templating:
            today = arrow.now()
            replacement_map = {
                "{{DATE}}": today.format("Do MMMM YYYY"),
                "{{NEXT_TUESDAY}}": _next_tuesday(today).format("Do MMMM YYYY"),
            }
            counts = self._apply_template_replacements(cover_file_id, replacement_map)

            try:
                pdf_data = self.gdrive_client.download_file(
                    file_id=cover_file_id,
                    file_name=f"Cover-{cover_file_id}",
                    cache_prefix="covers",
                    mime_type="application/pdf",
                    export=True,
                )
                return fitz.open(stream=pdf_data, filetype="pdf")
            except fitz.EmptyFileError as e:
                raise CoverGenerationException(
                    "Downloaded cover file is corrupted. Please check the file on Google Drive."
                ) from e
            finally:
                # Revert only the placeholders that were actually present. On a
                # Tuesday {{DATE}} and {{NEXT_TUESDAY}} format to the same string,
                # so inverting the whole map would rewrite the source doc's
                # {{DATE}} into {{NEXT_TUESDAY}} (or vice-versa). A cover uses one
                # placeholder or the other, never both, so reverting the present
                # ones restores the document exactly.
                revert_map = {
                    replacement_map[p]: p
                    for p in replacement_map
                    if counts.get(p, 0) > 0
                }
                if revert_map:
                    self._apply_template_replacements(cover_file_id, revert_map)
        else:
            # No templating, just download the file
            pdf_data = self.gdrive_client.download_file(
                file_id=cover_file_id,
                file_name=f"Cover-{cover_file_id}",
                cache_prefix="covers",
                mime_type="application/pdf",
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
    gdrive_client = GoogleDriveClient(cache=cache, credentials=creds)
    cover_config = config.get_settings().cover
    generator = CoverGenerator(gdrive_client, docs_write, cover_config)
    return generator.generate_cover(cover_file_id)
