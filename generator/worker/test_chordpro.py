from unittest.mock import MagicMock

from .chordpro import (
    build_chordpro,
    cells_per_bar,
    convert_chords_to_chordpro,
    detect_chord_only_line,
    format_as_grid,
    generate_song_chordpro,
    parse_doc_json,
    parse_metadata,
    parse_metadata_from_json,
    strip_annotations,
)


def _text_run(content, bold=False, italic=False):
    style = {}
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    return {"textRun": {"content": content, "textStyle": style}}


def _para(*runs):
    return {"paragraph": {"elements": list(runs)}}


# Minimal Docs API JSON fixture for Love Me Do
LOVE_ME_DO_DOC = {
    "body": {
        "content": [
            _para(_text_run("Love Me Do - The Beatles\n")),
            _para(
                _text_run("(Backing vocals)    ", italic=True),
                _text_run("Harmonies    148bpm    4/4    swing\n"),
            ),
            _para(_text_run("[harmonica]\n", italic=True)),
            _para(_text_run("\n")),
            _para(
                _text_run("(G) ", bold=True),
                _text_run("(C) ", bold=True),
                _text_run("(G) ", bold=True),
                _text_run("(C)\n", bold=True),
            ),
            _para(
                _text_run("(G)", bold=True),
                _text_run("Love, love me do "),
                _text_run("(C)\n", bold=True),
            ),
            _para(
                _text_run("You "),
                _text_run("(G)", bold=True),
                _text_run("know I love you "),
                _text_run("(C)\n", bold=True),
            ),
        ]
    }
}


# --- parse_metadata ---


def test_parse_metadata_bpm():
    metadata = parse_metadata("148bpm    4/4    swing")
    assert metadata["tempo"] == 148


def test_parse_metadata_time_sig():
    metadata = parse_metadata("148bpm    4/4    swing")
    assert metadata["time_sig"] == "4/4"


def test_parse_metadata_missing_bpm():
    metadata = parse_metadata("4/4")
    assert metadata["tempo"] is None
    assert metadata["time_sig"] == "4/4"


def test_parse_metadata_missing_time_sig():
    metadata = parse_metadata("120bpm")
    assert metadata["tempo"] == 120
    assert metadata["time_sig"] is None


def test_parse_metadata_both_missing():
    metadata = parse_metadata("Just lyrics")
    assert metadata["tempo"] is None
    assert metadata["time_sig"] is None


# --- parse_metadata_from_json ---


def test_parse_metadata_from_json_bpm():
    metadata = parse_metadata_from_json(LOVE_ME_DO_DOC)
    assert metadata["tempo"] == 148


def test_parse_metadata_from_json_time_sig():
    metadata = parse_metadata_from_json(LOVE_ME_DO_DOC)
    assert metadata["time_sig"] == "4/4"


def test_parse_metadata_from_json_empty_doc():
    metadata = parse_metadata_from_json({"body": {"content": []}})
    assert metadata["tempo"] is None
    assert metadata["time_sig"] is None


# --- cells_per_bar ---


def test_cells_per_bar_4_4():
    assert cells_per_bar("4/4") == 4


def test_cells_per_bar_3_4():
    assert cells_per_bar("3/4") == 3


def test_cells_per_bar_6_8():
    assert cells_per_bar("6/8") == 6


def test_cells_per_bar_none():
    assert cells_per_bar(None) == 4


def test_cells_per_bar_invalid():
    assert cells_per_bar("invalid") == 4


# --- detect_chord_only_line ---


def test_detect_chord_only_line_true():
    is_chord_only, chords = detect_chord_only_line("(G) (C) (G) (C)")
    assert is_chord_only is True
    assert chords == ["G", "C", "G", "C"]


def test_detect_chord_only_line_with_lyrics():
    is_chord_only, chords = detect_chord_only_line("(G)Love me do (C)")
    assert is_chord_only is False
    assert chords == ["G", "C"]


def test_detect_chord_only_line_no_chords():
    is_chord_only, chords = detect_chord_only_line("Love me do")
    assert is_chord_only is False
    assert chords == []


def test_detect_chord_only_line_whitespace_only():
    is_chord_only, chords = detect_chord_only_line("   ")
    assert is_chord_only is False
    assert chords == []


# --- format_as_grid ---


def test_format_as_grid_4_4():
    chords = ["G", "C", "G", "C"]
    grid = format_as_grid(chords, "4/4")
    expected = "| G C G C |"
    assert grid == expected


def test_format_as_grid_3_4():
    chords = ["G", "C", "G", "C", "D"]
    grid = format_as_grid(chords, "3/4")
    lines = grid.split("\n")
    assert len(lines) == 2
    assert "G C G" in lines[0]
    assert "C D ." in lines[1]


def test_format_as_grid_partial_bar():
    chords = ["G", "C"]
    grid = format_as_grid(chords, "4/4")
    assert "G C . ." in grid


def test_format_as_grid_empty():
    grid = format_as_grid([], "4/4")
    assert grid == ""


def test_format_as_grid_6_8():
    chords = ["G", "C", "G", "C", "G", "C", "D"]
    grid = format_as_grid(chords, "6/8")
    lines = grid.split("\n")
    assert len(lines) == 2
    assert "G C G C G C" in lines[0]
    assert "D . . . . ." in lines[1]


# --- convert_chords_to_chordpro ---


def test_convert_chords_to_chordpro():
    text = "(G)Love me do (C)"
    result = convert_chords_to_chordpro(text)
    assert result == "[G]Love me do [C]"


def test_convert_chords_to_chordpro_no_chords():
    text = "Love me do"
    result = convert_chords_to_chordpro(text)
    assert result == "Love me do"


def test_convert_chords_to_chordpro_complex_chord():
    text = "(G/B)Love (Cm7)me"
    result = convert_chords_to_chordpro(text)
    assert result == "[G/B]Love [Cm7]me"


# --- strip_annotations ---


def test_strip_annotations_stage_direction():
    result = strip_annotations("[harmonica]")
    assert result is None


def test_strip_annotations_inline():
    result = strip_annotations("[all] (G)Love me do (C)")
    assert result == "(G)Love me do (C)"


def test_strip_annotations_mid_line():
    result = strip_annotations("(G) (G) [no ukes] (D7)")
    assert result == "(G) (G) (D7)"


def test_strip_annotations_no_annotations():
    result = strip_annotations("(G)Love me do (C)")
    assert result == "(G)Love me do (C)"


def test_strip_annotations_multiple():
    result = strip_annotations("[intro] (G) [verse] (C)")
    assert result == "(G) (C)"


# --- parse_doc_json ---


def test_parse_doc_json_title():
    title, _ = parse_doc_json(LOVE_ME_DO_DOC)
    assert title == "Love Me Do"


def test_parse_doc_json_skips_metadata_paragraph():
    _, sections = parse_doc_json(LOVE_ME_DO_DOC)
    full = "\n".join(sections)
    assert "148bpm" not in full
    assert "4/4" not in full


def test_parse_doc_json_chord_only_becomes_grid():
    _, sections = parse_doc_json(LOVE_ME_DO_DOC, time_sig="4/4")
    full = "\n".join(sections)
    assert "{start_of_grid}" in full
    # Single-chord bars are padded with dots; each space-separated token = one bar
    assert "| G . . . | C . . . | G . . . | C . . . |" in full
    assert "{end_of_grid}" in full


def test_parse_doc_json_annotation_paragraph_kept():
    _, sections = parse_doc_json(LOVE_ME_DO_DOC, include_annotations=True)
    full = "\n".join(sections)
    assert "{comment: harmonica}" in full


def test_parse_doc_json_annotation_paragraph_stripped():
    _, sections = parse_doc_json(LOVE_ME_DO_DOC, include_annotations=False)
    full = "\n".join(sections)
    assert "harmonica" not in full


def test_parse_doc_json_inline_chords():
    _, sections = parse_doc_json(LOVE_ME_DO_DOC)
    full = "\n".join(sections)
    assert "[G]Love, love me do [C]" in full
    assert "You [G]know I love you [C]" in full


def test_parse_doc_json_inline_italic_stripped():
    doc = {
        "body": {
            "content": [
                _para(_text_run("Song\n")),
                _para(
                    _text_run("(G)", bold=True),
                    _text_run("do ", italic=True),
                    _text_run("lyrics"),
                ),
            ]
        }
    }
    _, sections = parse_doc_json(doc)
    assert "do" not in sections[0]
    assert "[G]" in sections[0]
    assert "lyrics" in sections[0]


def test_parse_doc_json_section_split_on_empty_para():
    doc = {
        "body": {
            "content": [
                _para(_text_run("Song\n")),
                _para(_text_run("(G)", bold=True), _text_run("first\n")),
                _para(_text_run("\n")),
                _para(_text_run("(C)", bold=True), _text_run("second\n")),
            ]
        }
    }
    _, sections = parse_doc_json(doc)
    assert len(sections) == 2


def test_parse_doc_json_empty_doc():
    title, sections = parse_doc_json({"body": {"content": []}})
    assert title == "Untitled"
    assert sections == []


def test_parse_doc_json_space_separated_chords_become_separate_bars():
    doc = {
        "body": {
            "content": [
                _para(_text_run("Song\n")),
                _para(
                    _text_run("(G) ", bold=True),
                    _text_run("(C) ", bold=True),
                    _text_run("(G)\n", bold=True),
                ),
            ]
        }
    }
    _, sections = parse_doc_json(doc, time_sig="4/4")
    full = "\n".join(sections)
    assert "| G . . . | C . . . | G . . . |" in full


def test_parse_doc_json_no_space_chords_become_one_bar():
    doc = {
        "body": {
            "content": [
                _para(_text_run("Song\n")),
                _para(_text_run("(X)(X)(X)(X)\n", bold=True)),
            ]
        }
    }
    _, sections = parse_doc_json(doc, time_sig="4/4")
    full = "\n".join(sections)
    assert "| X X X X |" in full


def test_parse_doc_json_mixed_spacing():
    doc = {
        "body": {
            "content": [
                _para(_text_run("Song\n")),
                _para(_text_run("(C) (X)(X)(X)(X) (F)\n", bold=True)),
            ]
        }
    }
    _, sections = parse_doc_json(doc, time_sig="4/4")
    full = "\n".join(sections)
    assert "| C . . . | X X X X | F . . . |" in full


# --- build_chordpro ---


def test_build_chordpro_basic():
    chordpro = build_chordpro(
        "Love Me Do",
        "The Beatles",
        ["[G]Love, love me do [C]"],
        {"tempo": 148, "time_sig": "4/4"},
    )
    assert "{title: Love Me Do}" in chordpro
    assert "{artist: The Beatles}" in chordpro
    assert "{tempo: 148}" in chordpro
    assert "{time: 4/4}" in chordpro
    assert "[G]Love, love me do [C]" in chordpro


def test_build_chordpro_no_artist():
    chordpro = build_chordpro("Untitled", "", ["[G]Some lyrics"], {})
    assert "{title: Untitled}" in chordpro
    assert "{artist:" not in chordpro


def test_build_chordpro_pre_formatted_grid():
    section = "{start_of_grid}\n| G C G C |\n{end_of_grid}"
    chordpro = build_chordpro("Test", "Artist", [section], {"time_sig": "4/4"})
    assert "{start_of_grid}" in chordpro
    assert "| G C G C |" in chordpro
    assert "{end_of_grid}" in chordpro


def test_build_chordpro_multiple_sections():
    sections = [
        "[G]First verse [C]",
        "[D]Second verse [A]",
        "{start_of_grid}\n| G C G C |\n{end_of_grid}",
    ]
    chordpro = build_chordpro("Multi", "Artist", sections, {"time_sig": "4/4"})
    assert "[G]First verse [C]" in chordpro
    assert "[D]Second verse [A]" in chordpro
    assert "{start_of_grid}" in chordpro


def test_build_chordpro_ends_with_newline():
    chordpro = build_chordpro("Test", "Artist", [], {})
    assert chordpro.endswith("\n")


def test_build_chordpro_empty_sections_skipped():
    chordpro = build_chordpro(
        "Test", "Artist", ["", "[G]Verse [C]", ""], {"time_sig": "4/4"}
    )
    assert "[G]Verse [C]" in chordpro


# --- generate_song_chordpro ---


def test_generate_song_chordpro_artist_from_file_name(tmp_path):
    docs_service = MagicMock()
    docs_service.documents().get(
        documentId="file-id"
    ).execute.return_value = LOVE_ME_DO_DOC

    dest = tmp_path / "love_me_do.cho"
    generate_song_chordpro(docs_service, "file-id", "Love Me Do - The Beatles", dest)

    content = dest.read_text()
    assert "{title: Love Me Do}" in content
    assert "{artist: The Beatles}" in content


def test_generate_song_chordpro_no_artist_when_no_dash(tmp_path):
    doc = {
        "body": {
            "content": [
                _para(_text_run("Untitled\n")),
                _para(_text_run("(G)", bold=True), _text_run("Some lyrics\n")),
            ]
        }
    }
    docs_service = MagicMock()
    docs_service.documents().get(documentId="file-id").execute.return_value = doc

    dest = tmp_path / "untitled.cho"
    generate_song_chordpro(docs_service, "file-id", "Untitled", dest)

    content = dest.read_text()
    assert "{artist:" not in content


def test_generate_song_chordpro_uses_space_as_bar_boundary(tmp_path):
    doc = {
        "body": {
            "content": [
                _para(_text_run("Waltz\n")),
                _para(_text_run("3/4    90bpm\n")),
                _para(
                    _text_run("(G) ", bold=True),
                    _text_run("(C) ", bold=True),
                    _text_run("(G)\n", bold=True),
                ),
            ]
        }
    }
    docs_service = MagicMock()
    docs_service.documents().get(documentId="file-id").execute.return_value = doc

    dest = tmp_path / "waltz.cho"
    generate_song_chordpro(docs_service, "file-id", "Waltz", dest)

    content = dest.read_text()
    # Single-chord bars padded to 3 beats for 3/4
    assert "| G . . | C . . | G . . |" in content
