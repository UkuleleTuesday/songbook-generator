import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import click

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


@dataclass
class TaggerConfig:
    """Configuration for a tagger function."""

    func: Callable[[Context], Any]
    only_if_unset: bool = False


# A list to hold all tagged functions
_TAGGERS: List[TaggerConfig] = []
tracer = get_tracer(__name__)

# Folder IDs for status checking.
# Ref: generator/common/config.py:DEFAULT_GDRIVE_FOLDER_IDS
FOLDER_ID_APPROVED = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"
FOLDER_ID_READY_TO_PLAY = "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM"

# Character for downward arrow, used for single strums.
DOWNWARD_ARROW = "↓"

# Pre-compiled regex patterns for metadata extraction.
CHORD_PATTERN = re.compile(r"\(([^)]+)\)")
ANNOTATION_PATTERN = re.compile(r"(\d+bpm|\d/\d)", re.IGNORECASE)
SWING_PATTERN = re.compile(r"\bswing\b", re.IGNORECASE)
GALLOP_PATTERN = re.compile(r"\bgallop\b", re.IGNORECASE)
BPM_PATTERN = re.compile(r"(\d+)bpm", re.IGNORECASE)
TIME_SIGNATURE_PATTERN = re.compile(r"(\d/\d)")


def tag(_func=None, *, only_if_unset: bool = False):
    """
    Decorator to register a function as a tag generator.

    Args:
        only_if_unset: If True, the tag will only be set if it's not
                       already present on the file.
    """

    def decorator(func: Callable[[Context], Any]) -> Callable[[Context], Any]:
        _TAGGERS.append(TaggerConfig(func=func, only_if_unset=only_if_unset))
        return func

    if _func is None:
        # Called as @tag(only_if_unset=True)
        return decorator
    # Called as @tag
    return decorator(_func)


class Tagger:
    def __init__(self, drive_service: Any, docs_service: Any):
        self.drive_service = drive_service
        self.docs_service = docs_service

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
            current_properties = file.properties.copy()
            for tagger_config in _TAGGERS:
                tagger_func = tagger_config.func
                tag_name = tagger_func.__name__

                if tagger_config.only_if_unset and tag_name in current_properties:
                    continue

                tag_value = tagger_func(context)
                if tag_value is not None:
                    new_properties[tag_name] = str(tag_value)

            click.echo(f"New properties: {json.dumps(new_properties)}")
            if new_properties:
                span.set_attribute("new_properties", json.dumps(new_properties))
                # Preserve existing properties by doing a read-modify-write.
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

    ordered_unique_notations = []
    seen_notations = set()

    song_body_elements = _get_song_body_elements(ctx.document)
    for element in song_body_elements:
        if "paragraph" in element:
            para = element["paragraph"]
            if "elements" in para:
                    for para_element in para["elements"]:
                        if "textRun" in para_element:
                            text_run = para_element["textRun"]
                            text_style = text_run.get("textStyle", {})
                            if text_style.get("bold"):
                                content = text_run.get("content", "")
                                matches = CHORD_PATTERN.findall(content)
                                for chord in matches:
                                    cleaned_chord = chord.replace(
                                        DOWNWARD_ARROW, ""
                                    ).strip()
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
    for para_text in _get_paragraph_texts(document):
        if ANNOTATION_PATTERN.search(para_text):
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
        if SWING_PATTERN.search(annotation_para):
            found_features.add("swing")
        if GALLOP_PATTERN.search(annotation_para):
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

    matches = BPM_PATTERN.findall(annotation_para)
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

    match = TIME_SIGNATURE_PATTERN.search(annotation_para)
    if match:
        return match.group(1)
    return None


def _get_song_body_elements(document: GoogleDocument) -> List[Dict[str, Any]]:
    """
    Extracts the structural elements of the song's body, which are assumed
    to start after the paragraph containing annotations (BPM, time signature).
    """
    doc_content = document.json.get("body", {}).get("content", [])
    if not doc_content:
        return []

    annotation_para_index = -1
    for i, element in enumerate(doc_content):
        if "paragraph" in element:
            para_text = ""
            for para_element in element["paragraph"].get("elements", []):
                if "textRun" in para_element:
                    para_text += para_element["textRun"].get("content", "")
            if ANNOTATION_PATTERN.search(para_text):
                annotation_para_index = i
                break

    start_index = annotation_para_index + 1 if annotation_para_index != -1 else 0
    return doc_content[start_index:]
