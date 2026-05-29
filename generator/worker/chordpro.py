import re
from pathlib import Path

from ..common.gdrive import GoogleDriveClient
from .pptx import parse_doc_text

_METADATA_RE = re.compile(r"\bbpm\b|\b\d+/\d+\b", re.IGNORECASE)
_CHORD_PATTERN = re.compile(r"\(([^)]+)\)")
_ANNOTATION_PATTERN = re.compile(r"\s*\[.*?\]")


def parse_metadata(text: str) -> dict:
    """Extract BPM and time signature from song text."""
    metadata = {"tempo": None, "time_sig": None}

    lines = text.split("\n")[:5]  # Check first few lines
    for line in lines:
        bpm_match = re.search(r"\b(\d+)\s*bpm\b", line, re.IGNORECASE)
        if bpm_match:
            metadata["tempo"] = int(bpm_match.group(1))

        time_match = re.search(r"\b(\d+/\d+)\b", line)
        if time_match:
            metadata["time_sig"] = time_match.group(1)

    return metadata


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


def build_chordpro(
    title: str,
    artist: str,
    sections: list[str],
    metadata: dict,
    include_annotations: bool = True,
    detect_sections: bool = False,
) -> str:
    """Build a complete ChordPro file from song components."""
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
        if not section.strip():
            lines.append("")
            continue

        section_lines = section.split("\n")
        for line in section_lines:
            if not line.strip():
                lines.append("")
                continue

            is_chord_only, chords = detect_chord_only_line(line)

            if is_chord_only:
                time_sig = metadata.get("time_sig", "4/4")
                grid = format_as_grid(chords, time_sig)
                lines.append("{start_of_grid}")
                lines.extend(grid.split("\n"))
                lines.append("{end_of_grid}")
            else:
                if not include_annotations:
                    stripped = strip_annotations(line)
                    if stripped is None:
                        continue
                    processed_line = convert_chords_to_chordpro(stripped)
                else:
                    annotation_match = re.match(r"^(\[.*?\])\s*(.*)", line)
                    if annotation_match:
                        annotation, rest = annotation_match.groups()
                        annotation_text = annotation[1:-1]
                        if rest:
                            processed_line = (
                                f"{{comment: {annotation_text}}}\n"
                                f"{convert_chords_to_chordpro(rest)}"
                            )
                        else:
                            processed_line = f"{{comment: {annotation_text}}}"
                    else:
                        processed_line = convert_chords_to_chordpro(line)

                for processed in processed_line.split("\n"):
                    if processed.strip():
                        lines.append(processed)

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_song_chordpro(
    gdrive_client: GoogleDriveClient,
    file_id: str,
    file_name: str,
    destination_path: Path,
    include_annotations: bool = True,
    detect_sections: bool = False,
) -> None:
    """Generate a ChordPro file from a Google Drive song document."""
    raw = gdrive_client.download_file(
        file_id=file_id,
        file_name=file_name,
        cache_prefix="song-chordpro",
        mime_type="text/plain",
        export=True,
        use_cache=False,
    )
    text = raw.decode("utf-8")

    title, sections = parse_doc_text(text, include_annotations=include_annotations)
    metadata = parse_metadata(text)

    artist = ""
    if " - " in title:
        title, artist = title.split(" - ", 1)

    chordpro_content = build_chordpro(
        title,
        artist,
        sections,
        metadata,
        include_annotations=include_annotations,
        detect_sections=detect_sections,
    )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(chordpro_content, encoding="utf-8")
