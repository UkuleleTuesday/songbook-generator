import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import click
from google import genai
from google.genai import types

from ..common.tracing import get_tracer
from ..worker.models import File

LLM_MODEL = "gemini-2.5-flash-lite"


@dataclass
class SongSheetGoogleDocument:
    """Represents the content of a Google Doc with helpers for song sheets."""

    json: Dict[str, Any]
    paragraph_texts: List[str] = field(init=False)
    annotation_paragraph_text: Optional[str] = field(init=False)
    song_body_elements: List[Dict[str, Any]] = field(init=False)

    def __post_init__(self):
        """Compute derived fields after the object has been initialized."""
        self.paragraph_texts = self._compute_paragraph_texts()
        self.annotation_paragraph_text = self._compute_annotation_paragraph_text()
        self.song_body_elements = self._compute_song_body_elements()

    def _compute_paragraph_texts(self) -> List[str]:
        """Extracts the text content of each paragraph from a document."""
        texts = []
        doc_content = self.json.get("body", {}).get("content", [])
        for element in doc_content:
            if "paragraph" in element:
                para_text = ""
                for para_element in element["paragraph"].get("elements", []):
                    if "textRun" in para_element:
                        para_text += para_element["textRun"].get("content", "")
                texts.append(para_text)
        return texts

    def _compute_annotation_paragraph_text(self) -> Optional[str]:
        """Finds and returns the text of the paragraph containing song annotations."""
        for para_text in self.paragraph_texts:
            if ANNOTATION_PATTERN.search(para_text):
                return para_text
        return None

    def _compute_song_body_elements(self) -> List[Dict[str, Any]]:
        """
        Extracts the structural elements of the song's body, which are assumed
        to start after the paragraph containing annotations (BPM, time signature).
        """
        doc_content = self.json.get("body", {}).get("content", [])
        if not doc_content:
            return []

        annotation_para_index = -1
        # Find the index of the annotation paragraph.
        for i, para_text in enumerate(self.paragraph_texts):
            if ANNOTATION_PATTERN.search(para_text):
                # This assumes paragraph_texts maps 1:1 to content elements with paragraphs
                # which is how _compute_paragraph_texts works.
                annotation_para_index = i
                break

        start_index = annotation_para_index + 1 if annotation_para_index != -1 else 0
        return doc_content[start_index:]


@dataclass
class Context:
    """Context object passed to tagger functions."""

    file: File
    file_name: str = ""
    document: Optional[SongSheetGoogleDocument] = None
    owner_name: Optional[str] = None
    genai_client: Optional[genai.Client] = None


@dataclass
class TaggerConfig:
    """Configuration for a tagger function."""

    func: Callable[[Context], Any]
    only_if_unset: bool = False


@dataclass
class LlmTaggerConfig:
    """Configuration for an LLM-backed tagger function."""

    func: Callable[["Context", Optional[str]], Optional[str]]
    prompt: str
    only_if_unset: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


# A list to hold all tagged functions
_TAGGERS: List[TaggerConfig] = []
# A list to hold all LLM-backed tagged functions
_LLM_TAGGERS: List[LlmTaggerConfig] = []
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


def llm_tag(
    *,
    prompt: str,
    only_if_unset: bool = False,
    **extra: Any,
):
    """
    Decorator to register a function as an LLM-backed tag generator.

    All @llm_tag functions are batched into a single LLM call that requests
    structured JSON output. The decorated function acts as a validator: it
    receives the Context and the raw string value from the LLM response, and
    returns the final tag value or None if the value is invalid.

    Args:
        prompt: Template string for the LLM prompt. Supports {song}, {artist},
                {year}, and {name} placeholders which are filled from the file's
                properties at call time. Any **extra kwargs are also available
                as placeholders.
        only_if_unset: If True, the tag will only be set if it's not
                       already present on the file.
        **extra: Additional keyword arguments made available as prompt template
                 placeholders and passed through to the validator function.
    """

    def decorator(
        func: Callable[["Context", Optional[str]], Optional[str]],
    ) -> Callable[["Context", Optional[str]], Optional[str]]:
        _LLM_TAGGERS.append(
            LlmTaggerConfig(
                func=func, prompt=prompt, only_if_unset=only_if_unset, extra=extra
            )
        )
        return func

    return decorator


def _run_llm_tags(ctx: Context, llm_taggers: List[LlmTaggerConfig]) -> Dict[str, str]:
    """
    Execute all applicable LLM-backed taggers in a single batched LLM call.

    Builds a compound prompt requesting a JSON object with one key per tagger,
    calls the LLM once, parses the structured response, then validates each
    value using its registered function.

    Returns a dict of {tag_name: validated_value} for fields that passed
    validation.
    """
    if not llm_taggers or ctx.genai_client is None:
        return {}

    with tracer.start_as_current_span("run_llm_tags") as span:
        tagger_names = [config.func.__name__ for config in llm_taggers]
        span.set_attribute("llm.model", LLM_MODEL)
        span.set_attribute("llm.taggers_count", len(llm_taggers))
        span.set_attribute("llm.tagger_names", ",".join(tagger_names))

        base_template_vars = {
            "song": ctx.file.properties.get("song", ctx.file_name),
            "artist": ctx.file.properties.get("artist", "unknown artist"),
            "year": ctx.file.properties.get("year", ""),
            "name": ctx.file_name,
        }

        fields = [config.func.__name__ for config in llm_taggers]
        prompts_section = "\n".join(
            f"- {config.func.__name__}: "
            f"{config.prompt.format_map({**base_template_vars, **config.extra})}"
            for config in llm_taggers
        )
        compound_prompt = (
            "Please answer the following questions about this song. "
            f"Return ONLY a valid JSON object with exactly these keys: "
            f"{', '.join(repr(f) for f in fields)}. "
            "Use a JSON null value for any field that is unknown.\n\n"
            f"{prompts_section}"
        )

        response = ctx.genai_client.models.generate_content(
            model=LLM_MODEL,
            contents=compound_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        raw_text = response.text.strip()
        span.add_event("llm_response_received", {"response_length": len(raw_text)})
        # Strip markdown code fences if present
        raw_text = re.sub(r"^```[^\n]*\n", "", raw_text)
        raw_text = raw_text.rstrip("`").strip()

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            click.echo(f"LLM returned invalid JSON: {raw_text!r}", err=True)
            span.add_event("json_parse_error", {"raw_text_preview": raw_text[:200]})
            span.set_attribute("llm.parse_error", True)
            span.set_attribute("llm.results_count", 0)
            return {}

        results = {}
        for config in llm_taggers:
            field_name = config.func.__name__
            raw_value = parsed.get(field_name)
            if raw_value is not None:
                raw_value = str(raw_value).strip()
            validated = config.func(ctx, raw_value, **config.extra)
            if validated is not None:
                results[field_name] = validated

        span.set_attribute("llm.results_count", len(results))
        span.set_attribute("llm.validated_tags", ",".join(results.keys()))

        return results


class Tagger:
    def __init__(
        self,
        drive_service: Any,
        docs_service: Any,
        trigger_field: Optional[str] = None,
        genai_client: Optional[genai.Client] = None,
        llm_tagging_enabled: bool = False,
    ):
        self.drive_service = drive_service
        self.docs_service = docs_service
        self.trigger_field = trigger_field
        self.genai_client = genai_client
        self.llm_tagging_enabled = llm_tagging_enabled

    def update_tags(self, file: File, dry_run: bool = False):
        """
        Update Google Drive file properties based on registered tag functions.

        This method builds a context for the file, which may include fetching
        the content of a Google Doc. It then calls each registered tagger
        function with this context. If a tagger returns a value, it's added
        to the file's properties.

        LLM-backed tags (@llm_tag) are batched into a single LLM call.
        """
        with tracer.start_as_current_span(
            "update_tags",
            attributes={
                "file.id": file.id,
                **({"trigger_field": self.trigger_field} if self.trigger_field else {}),
            },
        ) as span:
            # Build context, fetching doc content if necessary
            document = None
            if file.mimeType == "application/vnd.google-apps.document":
                doc_json = (
                    self.docs_service.documents().get(documentId=file.id).execute()
                )
                document = SongSheetGoogleDocument(json=doc_json)

            # Fetch file name and owner from Drive
            file_meta = (
                self.drive_service.files()
                .get(fileId=file.id, fields="name,owners(displayName)")
                .execute()
            )
            file_name = file_meta.get("name", "")
            span.set_attribute("file.name", file_name)
            owner_name = None
            if "owners" in file_meta and file_meta["owners"]:
                owner_name = file_meta["owners"][0].get("displayName")

            context = Context(
                file=file,
                file_name=file_name,
                document=document,
                owner_name=owner_name,
                genai_client=self.genai_client,
            )

            new_properties = {}
            current_properties = file.properties.copy()

            # Run regular (non-LLM) taggers
            for tagger_config in _TAGGERS:
                tagger_func = tagger_config.func
                tag_name = tagger_func.__name__

                if tagger_config.only_if_unset and tag_name in current_properties:
                    continue

                tag_value = tagger_func(context)
                if tag_value is not None:
                    value_str = str(tag_value)
                    key_bytes = len(tag_name.encode("utf-8"))
                    value_bytes = len(value_str.encode("utf-8"))
                    if key_bytes + value_bytes > 124:
                        click.echo(
                            f"  WARNING: Tag '{tag_name}' is too long "
                            f"({key_bytes + value_bytes} bytes > 124) and will be skipped.",
                            err=True,
                        )
                        span.add_event(
                            "tag_skipped_too_long",
                            {
                                "tag_name": tag_name,
                                "byte_count": key_bytes + value_bytes,
                            },
                        )
                        continue
                    new_properties[tag_name] = value_str

            # Collect applicable LLM taggers and run them in a single batched call
            span.set_attribute("llm_tags.enabled", self.llm_tagging_enabled)
            if not self.llm_tagging_enabled:
                click.echo("LLM tagging is disabled, skipping LLM tags.")
                llm_results = {}
            else:
                applicable_llm_taggers = [
                    config
                    for config in _LLM_TAGGERS
                    if not (
                        config.only_if_unset
                        and config.func.__name__ in current_properties
                    )
                ]
                span.set_attribute(
                    "llm_tags.applicable_count", len(applicable_llm_taggers)
                )
                llm_results = _run_llm_tags(context, applicable_llm_taggers)
            for tag_name, tag_value in llm_results.items():
                value_str = str(tag_value)
                key_bytes = len(tag_name.encode("utf-8"))
                value_bytes = len(value_str.encode("utf-8"))
                if key_bytes + value_bytes > 124:
                    click.echo(
                        f"  WARNING: Tag '{tag_name}' is too long "
                        f"({key_bytes + value_bytes} bytes > 124) and will be skipped.",
                        err=True,
                    )
                    span.add_event(
                        "tag_skipped_too_long",
                        {"tag_name": tag_name, "byte_count": key_bytes + value_bytes},
                    )
                    continue
                new_properties[tag_name] = value_str

            click.echo(f"New properties: {json.dumps(new_properties)}")
            if new_properties:
                span.set_attribute("new_properties", json.dumps(new_properties))
                # Preserve existing properties by doing a read-modify-write.
                click.echo(f"  Current properties: {json.dumps(current_properties)}")
                span.set_attribute("current_properties", json.dumps(current_properties))
                updated_properties = current_properties.copy()
                updated_properties.update(new_properties)
                click.echo(f"  Updated properties: {json.dumps(updated_properties)}")

                if self.trigger_field is not None:
                    current_trigger_value = current_properties.get(self.trigger_field)
                    new_trigger_value = updated_properties.get(self.trigger_field)
                    span.set_attribute(
                        "trigger_field.current_value", str(current_trigger_value)
                    )
                    span.set_attribute(
                        "trigger_field.new_value", str(new_trigger_value)
                    )
                    if current_trigger_value == new_trigger_value:
                        click.echo(
                            f"  Trigger field '{self.trigger_field}' unchanged, skipping update."
                        )
                        span.set_attribute(
                            "update_skipped.reason", "trigger_field_unchanged"
                        )
                        return
                elif updated_properties == current_properties:
                    click.echo("  Tags are identical, no update needed.")
                    span.set_attribute("update_skipped.reason", "tags_identical")
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@tag(only_if_unset=True)
def ready_to_play_date(ctx: Context) -> Optional[str]:
    """Records the datetime when a song was first marked as ready to play."""
    if FOLDER_ID_READY_TO_PLAY in ctx.file.parents:
        return _now_iso()
    return None


@tag(only_if_unset=True)
def approved_date(ctx: Context) -> Optional[str]:
    """Records the datetime when a song was first marked as approved."""
    if FOLDER_ID_APPROVED in ctx.file.parents:
        return _now_iso()
    return None


def _extract_all_chord_notations(ctx: Context) -> List[str]:
    """Extracts all unique, chord-like notations from a Google Doc."""
    if not ctx.document:
        return []

    ordered_unique_notations = []
    seen_notations = set()

    for element in ctx.document.song_body_elements:
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


@tag
def features(ctx: Context) -> Optional[str]:
    """Extracts special musical features from the document."""
    if not ctx.document:
        return None

    found_features = set()

    # Check for chucks from notations
    all_notations = _extract_all_chord_notations(ctx)
    if "X" in all_notations:
        found_features.add("chucks")

    # Check for other text-based features from annotation paragraphs
    if ctx.document.annotation_paragraph_text:
        if SWING_PATTERN.search(ctx.document.annotation_paragraph_text):
            found_features.add("swing")
        if GALLOP_PATTERN.search(ctx.document.annotation_paragraph_text):
            found_features.add("gallop")

    if not found_features:
        return None

    return ",".join(sorted(list(found_features)))


@tag(only_if_unset=True)
def tabber(ctx: Context) -> Optional[str]:
    """Extracts and cleans the file owner's name as the tabber."""
    if not ctx.owner_name:
        return None

    name = ctx.owner_name.split(".")[0]

    # TODO: Replace this with a more robust aliasing system.
    if name.lower() == "miguel":
        return "Mischa"

    return name.capitalize()


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
def song(ctx: Context) -> Optional[str]:
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
    if not ctx.document or not ctx.document.annotation_paragraph_text:
        return None

    matches = BPM_PATTERN.findall(ctx.document.annotation_paragraph_text)
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
    if not ctx.document or not ctx.document.annotation_paragraph_text:
        return None

    match = TIME_SIGNATURE_PATTERN.search(ctx.document.annotation_paragraph_text)
    if match:
        return match.group(1)
    return None


@llm_tag(
    prompt=(
        'What year was "{song}" by {artist} originally released? '
        "Reply with only the 4-digit year, or null if unknown."
    ),
    only_if_unset=True,
)
def year(ctx: Context, raw: Optional[str]) -> Optional[str]:
    """Looks up the original release year of the song via Gemini + Google Search."""
    if raw and re.fullmatch(r"\d{4}", raw):
        return raw
    return None


def _parse_duration(raw: str) -> Optional[str]:
    """Parse a duration string into HH:MM:SS format, or None if unparseable."""
    match = re.search(r"(\d+):(\d{2})", raw)
    if not match:
        return None
    minutes, seconds = int(match.group(1)), int(match.group(2))
    if seconds > 59:
        return None
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@llm_tag(
    prompt=(
        'What is the duration of "{song}" by {artist} ({year}) on its original studio release? '
        "Reply with only the duration in MM:SS format, or null if unknown."
    ),
    only_if_unset=True,
)
def duration(ctx: Context, raw: Optional[str]) -> Optional[str]:
    """Looks up the original track duration via Gemini + Google Search."""
    if not raw:
        return None
    return _parse_duration(raw)


@llm_tag(
    prompt=(
        'What are the musical genres of "{song}" by {artist}? '
        "List up to {max_genres} genres as a comma-separated list "
        '(e.g. "Rock,Pop"), or null if unknown.'
    ),
    only_if_unset=True,
    max_genres=3,
)
def genre(ctx: Context, raw: Optional[str], *, max_genres: int = 3) -> Optional[str]:
    """Looks up the genre(s) of the song via Gemini + Google Search."""
    if not raw:
        return None
    parts = [g.strip() for g in raw.split(",") if g.strip()][:max_genres]
    return ",".join(parts) if parts else None
