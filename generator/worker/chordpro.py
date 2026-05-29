import re
from pathlib import Path

_METADATA_RE = re.compile(r"\bbpm\b|\b\d+/\d+\b", re.IGNORECASE)
_CHORD_PATTERN = re.compile(r"\(([^)]+)\)")
_ANNOTATION_PATTERN = re.compile(r"\s*\[.*?\]")


def _para_plain_text(para: dict) -> str:
    return "".join(
        run["textRun"].get("content", "")
        for run in para.get("elements", [])
        if "textRun" in run
    )


def _is_bold(run: dict) -> bool:
    return run.get("textRun", {}).get("textStyle", {}).get("bold", False)


def _is_italic(run: dict) -> bool:
    return run.get("textRun", {}).get("textStyle", {}).get("italic", False)


def parse_metadata(text: str) -> dict:
    """Extract BPM and time signature from song text."""
    metadata = {"tempo": None, "time_sig": None}

    lines = text.split("\n")[:5]
    for line in lines:
        bpm_match = re.search(r"\b(\d+)\s*bpm\b", line, re.IGNORECASE)
        if bpm_match:
            metadata["tempo"] = int(bpm_match.group(1))

        time_match = re.search(r"\b(\d+/\d+)\b", line)
        if time_match:
            metadata["time_sig"] = time_match.group(1)

    return metadata


def parse_metadata_from_json(doc_json: dict) -> dict:
    """Extract BPM and time signature from a Docs API document."""
    for element in doc_json.get("body", {}).get("content", []):
        if "paragraph" not in element:
            continue
        text = _para_plain_text(element["paragraph"])
        if _METADATA_RE.search(text):
            return parse_metadata(text)
    return {"tempo": None, "time_sig": None}


def cells_per_bar(time_sig: str) -> int:
    """Get number of cells per bar for a time signature."""
    if not time_sig:
        return 4

    try:
        numerator = int(time_sig.split("/")[0])
        return numerator
    except (ValueError, IndexError):
        return 4


def detect_chord_only_line(line: str) -> tuple[bool, list[str]]:
    """Check if a line contains only chords (no lyrics)."""
    chords = _CHORD_PATTERN.findall(line)
    if not chords:
        return False, []

    line_without_chords = _CHORD_PATTERN.sub("", line).strip()
    is_chord_only = len(line_without_chords) == 0 or line_without_chords.isspace()

    return is_chord_only, chords


def format_as_grid(chords: list[str], time_sig: str) -> str:
    """Format chord list as ChordPro grid."""
    if not chords:
        return ""

    cells = cells_per_bar(time_sig)
    grid_lines = []

    for i in range(0, len(chords), cells):
        bar_chords = chords[i : i + cells]
        while len(bar_chords) < cells:
            bar_chords.append(".")

        bar = " ".join(bar_chords)
        grid_lines.append(f"| {bar} |")

    return "\n".join(grid_lines)


def convert_chords_to_chordpro(text: str) -> str:
    """Convert chord notation from (chord) to [chord]."""
    return _CHORD_PATTERN.sub(r"[\1]", text)


def strip_annotations(text: str) -> str | None:
    """Remove annotations from text, return None if line becomes empty."""
    result = _ANNOTATION_PATTERN.sub("", text).strip()
    return result if result else None


def _parse_chord_bars(text: str, time_sig: str = "4/4") -> list[list[str]]:
    """Split chord-only text into bars using whitespace as bar boundaries.

    A single chord per token is padded with dots to fill the bar (per ChordPro spec,
    cells determine duration; '.' = sustain/empty beat).

    '(C) (G)' in 4/4 → [['C','.','.','.''], ['G','.','.','.']]
    '(X)(X)(X)(X)' in 4/4 → [['X','X','X','X']]
    '(C) (X)(X)(X)(X) (F)' in 4/4 → [['C','.','.','.''], ['X','X','X','X'], ['F','.','.','.']]
    """
    cpb = cells_per_bar(time_sig)
    bars = []
    for token in text.strip().split():
        chords = _CHORD_PATTERN.findall(token)
        if not chords:
            continue
        if len(chords) == 1:
            bars.append(chords + ["."] * (cpb - 1))
        else:
            bars.append(chords)
    return bars


def parse_doc_json(
    doc_json: dict,
    include_annotations: bool = True,
    time_sig: str = "4/4",
) -> tuple[str, list[str]]:
    """Parse a Google Docs API JSON document into (title, ChordPro-formatted sections).

    Uses text run formatting to distinguish chords (bold) from annotations (italic)
    and lyrics (regular), avoiding the ambiguity of plain-text heuristics.
    """
    content = doc_json.get("body", {}).get("content", [])
    paragraphs = [el["paragraph"] for el in content if "paragraph" in el]

    if not paragraphs:
        return "Untitled", []

    title_line = _para_plain_text(paragraphs[0]).strip()
    title = title_line.split(" - ")[0].strip() or "Untitled"

    sections: list[str] = []
    current_lines: list[str] = []

    for para in paragraphs[1:]:
        plain = _para_plain_text(para).strip()

        if _METADATA_RE.search(plain):
            continue

        if not plain:
            if current_lines:
                sections.append("\n".join(current_lines))
                current_lines = []
            continue

        runs = [el for el in para.get("elements", []) if "textRun" in el]
        content_runs = [r for r in runs if r["textRun"].get("content", "").strip()]

        # All bold → chord-only paragraph → grid
        # Space between chord groups = bar boundary; no space = beats within same bar
        if content_runs and all(_is_bold(r) for r in content_runs):
            bars = _parse_chord_bars(plain, time_sig)
            if bars:
                grid_line = "| " + " | ".join(" ".join(bar) for bar in bars) + " |"
                current_lines.append("{start_of_grid}")
                current_lines.append(grid_line)
                current_lines.append("{end_of_grid}")
                continue

        # All italic → standalone annotation paragraph
        if content_runs and all(_is_italic(r) for r in content_runs):
            if include_annotations:
                annotation_text = plain.strip("[]() \t")
                current_lines.append(f"{{comment: {annotation_text}}}")
            continue

        # Mixed paragraph: process run by run
        line_parts = []
        for run in runs:
            text_run = run["textRun"]
            run_content = text_run.get("content", "").rstrip("\n")
            if not run_content:
                continue
            style = text_run.get("textStyle", {})

            if style.get("bold"):
                line_parts.append(convert_chords_to_chordpro(run_content))
            elif style.get("italic"):
                pass  # inline annotations don't map cleanly to ChordPro
            else:
                line_parts.append(run_content)

        line = "".join(line_parts).strip()
        if line:
            current_lines.append(line)

    if current_lines:
        sections.append("\n".join(current_lines))

    return title, sections


def build_chordpro(
    title: str,
    artist: str,
    sections: list[str],
    metadata: dict,
    include_annotations: bool = True,
    detect_sections: bool = False,
) -> str:
    """Assemble a ChordPro file from pre-formatted sections."""
    lines = []

    lines.append(f"{{title: {title}}}")
    if artist:
        lines.append(f"{{artist: {artist}}}")

    if metadata.get("tempo"):
        lines.append(f"{{tempo: {metadata['tempo']}}}")
    if metadata.get("time_sig"):
        lines.append(f"{{time: {metadata['time_sig']}}}")

    lines.append("")

    for section in sections:
        if section.strip():
            lines.append(section)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_song_chordpro(
    docs_service,
    file_id: str,
    file_name: str,
    destination_path: Path,
    include_annotations: bool = True,
    detect_sections: bool = False,
) -> None:
    """Generate a ChordPro file from a Google Drive song document."""
    doc_json = docs_service.documents().get(documentId=file_id).execute()

    metadata = parse_metadata_from_json(doc_json)
    time_sig = metadata.get("time_sig") or "4/4"

    title, sections = parse_doc_json(
        doc_json,
        include_annotations=include_annotations,
        time_sig=time_sig,
    )

    artist = ""
    if " - " in file_name:
        artist = file_name.split(" - ", 1)[1]

    chordpro_content = build_chordpro(
        title,
        artist,
        sections,
        metadata,
    )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(chordpro_content, encoding="utf-8")
