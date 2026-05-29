from unittest.mock import MagicMock

from .chordpro import (
    build_chordpro,
    cells_per_bar,
    convert_chords_to_chordpro,
    detect_chord_only_line,
    format_as_grid,
    generate_song_chordpro,
    parse_metadata,
    strip_annotations,
)

LOVE_ME_DO_TEXT = """\
Love Me Do - The Beatles

(Backing vocals)    Harmonies    148bpm    4/4    swing

[harmonica]

(G) (C) (G) (C)
(G)Love, love me do (C)
You (G)know I love you (C)
I'll (G)always be true (C)
"""


# --- parse_metadata ---


def test_parse_metadata_bpm():
    metadata = parse_metadata(LOVE_ME_DO_TEXT)
    assert metadata["tempo"] == 148


def test_parse_metadata_time_sig():
    metadata = parse_metadata(LOVE_ME_DO_TEXT)
    assert metadata["time_sig"] == "4/4"


def test_parse_metadata_missing_bpm():
    text = "Song Title\n\n4/4"
    metadata = parse_metadata(text)
    assert metadata["tempo"] is None
    assert metadata["time_sig"] == "4/4"


def test_parse_metadata_missing_time_sig():
    text = "Song Title\n\n120bpm"
    metadata = parse_metadata(text)
    assert metadata["tempo"] == 120
    assert metadata["time_sig"] is None


def test_parse_metadata_both_missing():
    text = "Song Title\n\nJust lyrics"
    metadata = parse_metadata(text)
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


# --- build_chordpro ---


def test_build_chordpro_basic():
    chordpro = build_chordpro(
        "Love Me Do",
        "The Beatles",
        ["(G)Love, love me do (C)"],
        {"tempo": 148, "time_sig": "4/4"},
        include_annotations=True,
    )
    assert "{title: Love Me Do}" in chordpro
    assert "{artist: The Beatles}" in chordpro
    assert "{tempo: 148}" in chordpro
    assert "{time: 4/4}" in chordpro
    assert "[G]Love, love me do [C]" in chordpro


def test_build_chordpro_no_artist():
    chordpro = build_chordpro(
        "Untitled",
        "",
        ["(G)Some lyrics"],
        {},
        include_annotations=True,
    )
    assert "{title: Untitled}" in chordpro
    assert "{artist:" not in chordpro


def test_build_chordpro_chord_only_line():
    chordpro = build_chordpro(
        "Test Song",
        "Artist",
        ["(G) (C) (G) (C)"],
        {"time_sig": "4/4"},
        include_annotations=True,
    )
    assert "{start_of_grid}" in chordpro
    assert "{end_of_grid}" in chordpro
    assert "| G C G C |" in chordpro


def test_build_chordpro_strip_annotations():
    chordpro = build_chordpro(
        "Test",
        "Artist",
        ["[verse]\n(G)Love me do (C)"],
        {"time_sig": "4/4"},
        include_annotations=False,
    )
    assert "[verse]" not in chordpro
    assert "[G]Love me do [C]" in chordpro


def test_build_chordpro_keep_annotations():
    chordpro = build_chordpro(
        "Test",
        "Artist",
        ["[harmonica]\n(G)Love me do (C)"],
        {"time_sig": "4/4"},
        include_annotations=True,
    )
    assert "{comment: harmonica}" in chordpro
    assert "[G]Love me do [C]" in chordpro


def test_build_chordpro_multiple_sections():
    sections = [
        "(G)First verse (C)",
        "(D)Second verse (A)",
        "(G) (C) (G) (C)",
    ]
    chordpro = build_chordpro(
        "Multi",
        "Artist",
        sections,
        {"time_sig": "4/4"},
        include_annotations=True,
    )
    assert "[G]First verse [C]" in chordpro
    assert "[D]Second verse [A]" in chordpro
    assert "{start_of_grid}" in chordpro


def test_build_chordpro_ends_with_newline():
    chordpro = build_chordpro(
        "Test",
        "Artist",
        [],
        {},
        include_annotations=True,
    )
    assert chordpro.endswith("\n")


def test_build_chordpro_empty_sections():
    chordpro = build_chordpro(
        "Test",
        "Artist",
        ["", "(G)Verse (C)", ""],
        {"time_sig": "4/4"},
        include_annotations=True,
    )
    assert "[G]Verse [C]" in chordpro


def test_build_chordpro_3_4_grid():
    chordpro = build_chordpro(
        "Waltz",
        "Artist",
        ["(G) (C) (G) (C) (D)"],
        {"time_sig": "3/4"},
        include_annotations=True,
    )
    assert "{start_of_grid}" in chordpro
    lines = chordpro.split("\n")
    grid_lines = [line for line in lines if "|" in line]
    assert len(grid_lines) == 2


# --- generate_song_chordpro ---


def test_generate_song_chordpro_artist_from_file_name(tmp_path):
    gdrive_client = MagicMock()
    gdrive_client.download_file.return_value = LOVE_ME_DO_TEXT.encode("utf-8")

    dest = tmp_path / "love_me_do.cho"
    generate_song_chordpro(gdrive_client, "file-id", "Love Me Do - The Beatles", dest)

    content = dest.read_text()
    assert "{title: Love Me Do}" in content
    assert "{artist: The Beatles}" in content


def test_generate_song_chordpro_no_artist_when_no_dash(tmp_path):
    gdrive_client = MagicMock()
    gdrive_client.download_file.return_value = b"Untitled\n\n(G)Some lyrics\n"

    dest = tmp_path / "untitled.cho"
    generate_song_chordpro(gdrive_client, "file-id", "Untitled", dest)

    content = dest.read_text()
    assert "{artist:" not in content
