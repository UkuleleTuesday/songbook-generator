import json
import re
from typing import Any, Callable, List, Optional

import click
from googleapiclient.discovery import build

from ..common.tracing import get_tracer
from ..worker.models import File

# A list to hold all tagged functions
_TAGGERS: List[Callable[[File, Any], Any]] = []
tracer = get_tracer(__name__)

# Folder IDs for status checking.
# Ref: generator/common/config.py:DEFAULT_GDRIVE_FOLDER_IDS
FOLDER_ID_APPROVED = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"
FOLDER_ID_READY_TO_PLAY = "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM"


def tag(func: Callable[[File, Any], Any]) -> Callable[[File, Any], Any]:
    """Decorator to register a function as a tag generator."""
    _TAGGERS.append(func)
    return func


class Tagger:
    def __init__(self, drive_service: Any):
        self.drive_service = drive_service
        self.docs_service = build("docs", "v1", credentials=drive_service._credentials)

    def update_tags(self, file: File):
        """
        Update Google Drive file properties based on registered tag functions.

        For each function decorated with @tag, this function calls it with the
        file object and a context object (self). If the function returns a value
        other than None, it updates the file's `properties` with the function
        name as the key and the return value as the value.
        """
        with tracer.start_as_current_span(
            "update_tags", attributes={"file.id": file.id, "file.name": file.name}
        ) as span:
            new_properties = {}
            for tagger in _TAGGERS:
                tag_name = tagger.__name__
                tag_value = tagger(file, self)
                if tag_value is not None:
                    new_properties[tag_name] = str(tag_value)

            click.echo(f"New properties: {json.dumps(new_properties)}")
            if new_properties:
                span.set_attribute("new_properties", json.dumps(new_properties))
                # Preserve existing properties by doing a read-modify-write.
                current_properties = file.properties.copy()
                click.echo(f"  Current properties: {json.dumps(current_properties)}")
                span.set_attribute("current_properties", json.dumps(current_properties))
                updated_properties = current_properties.copy()
                updated_properties.update(new_properties)
                click.echo(f"  Updated properties: {json.dumps(updated_properties)}")

                if updated_properties == current_properties:
                    click.echo("  Tags are identical, no update needed.")
                    span.set_attribute("update_skipped", "true")
                    return

                self.drive_service.files().update(
                    fileId=file.id,
                    body={"properties": updated_properties},
                    fields="properties",
                ).execute()


@tag
def status(file: File, ctx: Tagger) -> Optional[str]:
    """Determine the status of a file based on its parent folder."""
    if FOLDER_ID_APPROVED in file.parents:
        return "APPROVED"
    if FOLDER_ID_READY_TO_PLAY in file.parents:
        return "READY_TO_PLAY"
    return None


@tag
def chords(file: File, ctx: Tagger) -> Optional[str]:
    """Extracts unique chords from a Google Doc in order of appearance."""
    if file.mimeType != "application/vnd.google-apps.document":
        return None

    document = ctx.docs_service.documents().get(documentId=file.id).execute()

    ordered_unique_chords = []
    seen_chords = set()
    chord_pattern = re.compile(r"\(([^)]+)\)")

    if "body" in document and "content" in document["body"]:
        for element in document["body"]["content"]:
            if "paragraph" in element:
                para = element["paragraph"]
                if "elements" in para:
                    for para_element in para["elements"]:
                        if "textRun" in para_element:
                            text_run = para_element["textRun"]
                            text_style = text_run.get("textStyle", {})
                            if text_style.get("bold"):
                                content = text_run.get("content", "")
                                matches = chord_pattern.findall(content)
                                for chord in matches:
                                    cleaned_chord = chord.replace("\u2193", "").strip()
                                    if (
                                        cleaned_chord
                                        and cleaned_chord not in seen_chords
                                    ):
                                        ordered_unique_chords.append(cleaned_chord)
                                        seen_chords.add(cleaned_chord)

    if not ordered_unique_chords:
        return None

    return ",".join(ordered_unique_chords)
