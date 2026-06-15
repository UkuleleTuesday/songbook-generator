import fitz

from . import toc_parse
from .changelog import short_key
from .worker import toc
from .worker.models import File


def test_extract_glyph_lines_strips_glyph_marker_and_page_numbers():
    lines = [
        "Table of Contents",
        "◕ 9 to 5 - Dolly Parton",
        "4",
        "..............................",
        "○ All The Small Things - Blink-182",
        "8",
        "◔ Ready Song - Artist*",  # WIP marker stripped
        "12",
    ]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == [
        "9 to 5 - Dolly Parton",
        "All The Small Things - Blink-182",
        "Ready Song - Artist",
    ]


def test_extract_strips_configured_postfix_and_marker_any_order():
    lines = ["◕ Monster Mash - Bobby Pickett 🎃", "● Spooky - Artist*🎃"]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=["🎃"])
    assert songs == ["Monster Mash - Bobby Pickett", "Spooky - Artist"]


def test_extract_strips_unknown_trailing_emoji_marker():
    # Historical editions appended themed emoji we have no config for.
    lines = ["◕ Hotel California - The Eagles 🎻", "● Creep - Radiohead 🎸️"]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == ["Hotel California - The Eagles", "Creep - Radiohead"]


def test_extract_strips_themed_letter_postfix_token():
    # A real case: a themed postfix rendered as a Greek-letter glyph (U+1F33),
    # which is a *letter* category, not a symbol — must still be stripped.
    lines = ["◕ Creep - Radiohead* ἳ", "◔ Candy - Paolo Nutini ἳ"]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == ["Creep - Radiohead", "Candy - Paolo Nutini"]


def test_extract_cuts_marker_with_glued_page_number():
    # The themed marker can render with the page number glued on (no space).
    lines = ["◑ Happy Xmas (War is Over) - John Lennon, Yoko Ono Ἴ104"]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == ["Happy Xmas (War is Over) - John Lennon, Yoko Ono"]


def test_extract_cuts_truncation_ellipsis_and_marker():
    lines = ["◔ Merry Christmas (I Don't Want to Fight... Ἴ"]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == ["Merry Christmas (I Don't Want to Fight"]


def test_extract_keeps_real_non_ascii_words():
    # Don't eat legitimate accented/foreign title words.
    lines = ["○ Ça plan pour moi - Plastic Bertrand", "○ 99 Luftballons - Nena"]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == ["Ça plan pour moi - Plastic Bertrand", "99 Luftballons - Nena"]


def test_extract_dash_fallback_when_no_glyphs():
    lines = [
        "Table of Contents",
        "Wonderwall - Oasis",
        "5",
        "Imagine - John Lennon",
        "6",
    ]
    songs = toc_parse.extract_songs_from_lines(lines, postfixes=[])
    assert songs == ["Wonderwall - Oasis", "Imagine - John Lennon"]


def test_extract_dedupes_preserving_order():
    lines = ["○ A - X", "○ B - Y", "○ A - X"]
    assert toc_parse.extract_songs_from_lines(lines, postfixes=[]) == ["A - X", "B - Y"]


def test_find_toc_pages_uses_page_indices():
    doc = fitz.open()
    for _ in range(5):
        doc.new_page()
    pages = toc_parse.find_toc_pages(
        doc, page_indices={"table_of_contents": {"first_page": 3, "last_page": 4}}
    )
    assert pages == [2, 3]
    doc.close()


def _assemble_songbook(files, cover_preface=2):
    """Render a real TOC via the production generator and assemble a doc that
    looks like a songbook (cover/preface + TOC pages + one page per song)."""
    tp, _ = toc.build_table_of_contents(files, 0)
    page_offset = cover_preface + len(tp)
    tp.close()
    tp, _ = toc.build_table_of_contents(files, page_offset)
    doc = fitz.open()
    for _ in range(cover_preface):
        doc.new_page()
    toc_start = len(doc)
    doc.insert_pdf(tp)
    toc_pages = len(doc) - toc_start
    for _ in files:
        doc.new_page()
    page_indices = {
        "table_of_contents": {
            "first_page": toc_start + 1,
            "last_page": toc_start + toc_pages,
        }
    }
    return doc, page_indices


def test_parse_toc_songs_roundtrip_recovers_all_songs():
    """The parser recovers exactly the songs the real TOC generator rendered."""
    names = [
        "9 to 5 - Dolly Parton",
        "Crocodile Rock - Elton John",
        "I Want to Break Free - Queen",
        "(You're the) Devil in Disguise - Elvis Presley",
        "Wonderwall - Oasis",
    ]
    files = [File(id=str(i), name=n) for i, n in enumerate(names)]
    doc, page_indices = _assemble_songbook(files)

    parsed = toc_parse.parse_toc_songs(doc, page_indices=page_indices)
    assert {short_key(p) for p in parsed} == {short_key(n) for n in names}
    doc.close()


def test_parse_toc_songs_roundtrip_without_page_indices():
    """Heuristic page detection finds the TOC when no manifest page_indices."""
    names = [
        "Angels - Robbie Williams",
        "Jolene - Dolly Parton",
        "Hey Jude - The Beatles",
    ]
    files = [File(id=str(i), name=n) for i, n in enumerate(names)]
    doc, _ = _assemble_songbook(files)

    parsed = toc_parse.parse_toc_songs(doc)  # no page_indices -> heuristic
    assert {short_key(p) for p in parsed} == {short_key(n) for n in names}
    doc.close()
