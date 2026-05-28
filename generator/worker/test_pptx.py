"""Tests for generator.worker.pptx – PPTX generation logic."""

import zipfile
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from ..worker.pptx import generate_song_pptx, parse_sections


# ─────────────────────────────────────────────────────────────────────────────
# parse_sections
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_sections_simple():
    text = "[G]Verse one\n\n[C]Verse two"
    assert parse_sections(text) == [["[G]Verse one"], ["[C]Verse two"]]


def test_parse_sections_multi_line_section():
    text = "[G]Line one\n[C]Line two\n\n[D]Bridge"
    assert parse_sections(text) == [["[G]Line one", "[C]Line two"], ["[D]Bridge"]]


def test_parse_sections_strips_blank_lines_around_text():
    text = "\n\n[G]Only section\n\n"
    assert parse_sections(text) == [["[G]Only section"]]


def test_parse_sections_empty_text():
    assert parse_sections("") == []


def test_parse_sections_only_whitespace():
    assert parse_sections("   \n\n   ") == []


def test_parse_sections_multiple_blank_lines_as_separator():
    text = "[G]Verse\n\n\n\n[C]Chorus"
    sections = parse_sections(text)
    assert len(sections) == 2
    assert sections[0] == ["[G]Verse"]
    assert sections[1] == ["[C]Chorus"]


# ─────────────────────────────────────────────────────────────────────────────
# generate_song_pptx
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_pptx(tmp_path) -> Path:
    return tmp_path / "song.pptx"


def _slide_texts(pptx_path: Path):
    """Return a list of text strings, one per slide (joined text box content)."""
    prs = Presentation(str(pptx_path))
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                for sub in shape.shapes:
                    if sub.has_text_frame and sub.text_frame.text.strip():
                        texts.append(sub.text_frame.text)
    return texts


def test_generate_pptx_creates_file(tmp_pptx):
    generate_song_pptx("My Song", "[G]Hello world", tmp_pptx)
    assert tmp_pptx.exists()
    assert tmp_pptx.stat().st_size > 0


def test_generate_pptx_slide_count_matches_sections(tmp_pptx):
    text = "[G]Verse 1\n\n[C]Chorus\n\n[D]Bridge"
    generate_song_pptx("My Song", text, tmp_pptx)
    prs = Presentation(str(tmp_pptx))
    assert len(prs.slides) == 3


def test_generate_pptx_empty_text_creates_one_slide(tmp_pptx):
    generate_song_pptx("My Song", "", tmp_pptx)
    prs = Presentation(str(tmp_pptx))
    assert len(prs.slides) == 1


def test_generate_pptx_first_slide_has_title(tmp_pptx):
    generate_song_pptx("Love Me Do", "[G]Verse 1", tmp_pptx)
    texts = _slide_texts(tmp_pptx)
    assert len(texts) >= 1
    assert "Love Me Do" in texts[0]


def test_generate_pptx_subsequent_slides_no_title(tmp_pptx):
    text = "[G]Verse 1\n\n[C]Chorus"
    generate_song_pptx("My Song", text, tmp_pptx)
    texts = _slide_texts(tmp_pptx)
    assert len(texts) == 2
    assert "My Song" not in texts[1]


def test_generate_pptx_content_on_correct_slides(tmp_pptx):
    text = "[G]Verse 1\n\n[D]Bridge\n\n[C]Chorus"
    generate_song_pptx("Test Song", text, tmp_pptx)
    texts = _slide_texts(tmp_pptx)
    assert "[G]Verse 1" in texts[0]
    assert "[D]Bridge" in texts[1]
    assert "[C]Chorus" in texts[2]


def test_generate_pptx_black_background(tmp_pptx):
    generate_song_pptx("My Song", "[G]Hello", tmp_pptx)
    with zipfile.ZipFile(tmp_pptx) as z:
        with z.open("ppt/slides/slide1.xml") as f:
            xml = f.read().decode()
    assert 'val="000000"' in xml


def test_generate_pptx_blue_border(tmp_pptx):
    generate_song_pptx("My Song", "[G]Hello", tmp_pptx)
    with zipfile.ZipFile(tmp_pptx) as z:
        with z.open("ppt/slides/slide1.xml") as f:
            xml = f.read().decode()
    assert "38B6FF" in xml


def test_generate_pptx_slide_dimensions(tmp_pptx):
    generate_song_pptx("My Song", "[G]Hello", tmp_pptx)
    prs = Presentation(str(tmp_pptx))
    assert prs.slide_width.emu == 13716000
    assert prs.slide_height.emu == 10287000


def test_generate_pptx_creates_parent_dirs(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "song.pptx"
    generate_song_pptx("My Song", "[G]Hello", nested)
    assert nested.exists()


def test_generate_pptx_multi_line_section(tmp_pptx):
    text = "[G]Line 1\n[C]Line 2\n\n[D]Bridge"
    generate_song_pptx("My Song", text, tmp_pptx)
    texts = _slide_texts(tmp_pptx)
    assert "[G]Line 1" in texts[0]
    assert "[C]Line 2" in texts[0]
    assert "[D]Bridge" in texts[1]


def test_generate_pptx_special_characters(tmp_pptx):
    """Song content with apostrophes, brackets etc. should not raise."""
    text = "[G]I'll always be true [C] & more <test>"
    generate_song_pptx("Test & Song", text, tmp_pptx)
    texts = _slide_texts(tmp_pptx)
    assert "Test & Song" in texts[0]
    assert "[G]I'll always be true [C] & more <test>" in texts[0]
