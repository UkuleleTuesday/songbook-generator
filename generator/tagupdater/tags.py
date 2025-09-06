import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional

import click
from googleapiclient.discovery import build

from ..common.tracing import get_tracer
from ..worker.models import File


@dataclass
class GoogleDocument:
    """Represents the content of a Google Doc."""

    json: Dict[str, Any]


@dataclass
class Context:
    """Context object passed to tagger functions."""

    file: File
    document: Optional[GoogleDocument] = None


# A list to hold all tagged functions
_TAGGERS: List[Callable[[Context], Any]] = []
tracer = get_tracer(__name__)

# Folder IDs for status checking.
# Ref: generator/common/config.py:DEFAULT_GDRIVE_FOLDER_IDS
FOLDER_ID_APPROVED = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"
FOLDER_ID_READY_TO_PLAY = "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM"


def tag(func: Callable[[Context], Any]) -> Callable[[Context], Any]:
    """Decorator to register a function as a tag generator."""
    _TAGGERS.append(func)
    return func


class Tagger:
    def __init__(self, credentials: Any):
        self.drive_service = build("drive", "v3", credentials=credentials)
        self.docs_service = build("docs", "v1", credentials=credentials)

    def update_tags(self, file: File, dry_run: bool = False):
        """
        Update Google Drive file properties based on registered tag functions.

        This method builds a context for the file, which may include fetching
        the content of a Google Doc. It then calls each registered tagger
        function with this context. If a tagger returns a value, it's added
        to the file's properties.
        """
        with tracer.start_as_current_span(
            "update_tags", attributes={"file.id": file.id, "file.name": file.name}
        ) as span:
            # Build context, fetching doc content if necessary
            document = None
            if file.mimeType == "application/vnd.google-apps.document":
                doc_json = (
                    self.docs_service.documents().get(documentId=file.id).execute()
                )
                document = GoogleDocument(json=doc_json)
            context = Context(file=file, document=document)

            new_properties = {}
            for tagger in _TAGGERS:
                tag_name = tagger.__name__
                tag_value = tagger(context)
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

                if dry_run:
                    click.echo("  DRY RUN: Skipping actual update.")
                    span.set_attribute("dry_run", "true")
                    return

                self.drive_service.files().update(
                    fileId=file.id,
                    body={"properties": updated_properties},
                    fields="properties",
                ).execute()


@tag
def status(ctx: Context) -> Optional[str]:
    """Determine the status of a file based on its parent folder."""
    if FOLDER_ID_APPROVED in ctx.file.parents:
        return "APPROVED"
    if FOLDER_ID_READY_TO_PLAY in ctx.file.parents:
        return "READY_TO_PLAY"
    return None


def _extract_all_chord_notations(ctx: Context) -> List[str]:
    """Extracts all unique, chord-like notations from a Google Doc."""
    if not ctx.document:
        return []

    document = ctx.document.json
    ordered_unique_notations = []
    seen_notations = set()
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
                                        and cleaned_chord not in seen_notations
                                    ):
                                        ordered_unique_notations.append(cleaned_chord)
                                        seen_notations.add(cleaned_chord)

    return ordered_unique_notations


@tag
def chords(ctx: Context) -> Optional[str]:
    """Extracts unique musical chords from a Google Doc in order of appearance."""
    all_notations = _extract_all_chord_notations(ctx)
    musical_chords = [c for c in all_notations if c not in ("N/C", "X")]

    if not musical_chords:
        return None

    return ",".join(musical_chords)


def _get_full_text(document: GoogleDocument) -> str:
    """A helper to extract the full text content from a document."""
    full_text = ""
    if "body" in document.json and "content" in document.json["body"]:
        for element in document.json["body"]["content"]:
            if "paragraph" in element:
                for para_element in element["paragraph"].get("elements", []):
                    if "textRun" in para_element:
                        full_text += para_element["textRun"].get("content", "")
    return full_text


def _get_paragraph_texts(document: GoogleDocument) -> List[str]:
    """A helper to extract the text content of each paragraph from a document."""
    paragraph_texts = []
    if "body" in document.json and "content" in document.json["body"]:
        for element in document.json["body"]["content"]:
            if "paragraph" in element:
                para_text = ""
                for para_element in element["paragraph"].get("elements", []):
                    if "textRun" in para_element:
                        para_text += para_element["textRun"].get("content", "")
                paragraph_texts.append(para_text)
    return paragraph_texts


def _get_annotation_paragraph_text(document: GoogleDocument) -> Optional[str]:
    """Finds and returns the text of the paragraph containing song annotations."""
    annotation_pattern = re.compile(r"(\d+bpm|\d/\d)", re.IGNORECASE)
    for para_text in _get_paragraph_texts(document):
        if annotation_pattern.search(para_text):
            return para_text
    return None


@tag
def features(ctx: Context) -> Optional[str]:
    """Extracts special musical features from the document."""
    if not ctx.document:
        return None

    found_features = set()

    # Check for chucks and no-chords from notations
    all_notations = _extract_all_chord_notations(ctx)
    if "X" in all_notations:
        found_features.add("chucks")
    if "N/C" in all_notations:
        found_features.add("no_chord")

    # Check for other text-based features from annotation paragraphs
    annotation_para = _get_annotation_paragraph_text(ctx.document)
    if annotation_para:
        if re.search(r"\bswing\b", annotation_para, re.IGNORECASE):
            found_features.add("swing")
        if re.search(r"\bgallop\b", annotation_para, re.IGNORECASE):
            found_features.add("gallop")

    if not found_features:
        return None

    return ",".join(sorted(list(found_features)))


@tag
def artist(ctx: Context) -> Optional[str]:
    """Extracts the artist from the document title."""
    if not ctx.document:
        return None
    title = ctx.document.json.get("title", "")
    if " - " in title:
        return title.split(" - ", 1)[1].strip()
    return None


@tag
def song_title(ctx: Context) -> Optional[str]:
    """Extracts the song title from the document title."""
    if not ctx.document:
        return None
    title = ctx.document.json.get("title", "")
    if " - " in title:
        return title.split(" - ", 1)[0].strip()
    return title


@tag
def bpm(ctx: Context) -> Optional[str]:
    """Extracts all unique BPM values from the document body as comma-separated list."""
    if not ctx.document:
        return None
    annotation_para = _get_annotation_paragraph_text(ctx.document)
    if not annotation_para:
        return None

    matches = re.findall(r"(\d+)bpm", annotation_para, re.IGNORECASE)
    if matches:
        # Remove duplicates while preserving order
        unique_matches = []
        seen = set()
        for match in matches:
            if match not in seen:
                unique_matches.append(match)
                seen.add(match)
        return ",".join(unique_matches)
    return None


@tag
def time_signature(ctx: Context) -> Optional[str]:
    """Extracts the time signature from the document body."""
    if not ctx.document:
        return None
    annotation_para = _get_annotation_paragraph_text(ctx.document)
    if not annotation_para:
        return None

    match = re.search(r"(\d/\d)", annotation_para)
    if match:
        return match.group(1)
    return None
