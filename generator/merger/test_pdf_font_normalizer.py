import re

import fitz
import pytest

from .pdf_font_normalizer import normalize_pdf_fonts, SUBSET_FONT_RE


def _get_font_names(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    fonts = set()
    for page in doc:
        for font in page.get_fonts():
            # font[2] is the font name as bytes
            fonts.add(font[2].decode("utf-8", "ignore"))
    doc.close()
    return fonts


@pytest.fixture
def sample_pdf_with_subset_font():
    """Creates a simple PDF with a font name that mimics a subset font."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Hello World", fontname="helv", fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()

    # To test the logic, we manually replace a known font name in the PDF's
    # raw bytes with a fake subset name. This is a pragmatic way to create
    # a test case without needing a real (and large) GDocs export.
    return pdf_bytes.replace(b"/Helv", b"/AAAAAA+Verdana")


def test_subset_font_regex():
    """Test the regex for identifying subset fonts."""
    assert SUBSET_FONT_RE.match("AAAAAA+Verdana-Bold")
    assert SUBSET_FONT_RE.match("BCDFGH+ArialMT")
    assert not SUBSET_FONT_RE.match("Verdana-Bold")
    assert not SUBSET_FONT_RE.match("Arial")
    assert not SUBSET_FONT_RE.match("A_Random_Font")


def test_normalize_pdf_fonts_replaces_subsets(mocker, sample_pdf_with_subset_font):
    """Test that the normalizer identifies and attempts to replace a subset font."""
    mock_find = mocker.patch(
        "generator.merger.pdf_font_normalizer.find_font_path",
        return_value="/fake/path/to/Verdana.ttf",
    )
    mock_embed = mocker.patch("fitz.Document.embed_font")
    mock_clean = mocker.patch("fitz.Document.clean_contents")

    # Run the normalizer
    normalize_pdf_fonts(sample_pdf_with_subset_font)

    # 1. It should have looked for the base font name "Verdana".
    mock_find.assert_called_once_with("Verdana")

    # 2. It should have attempted to embed the full font.
    mock_embed.assert_called_once_with(
        fontfile="/fake/path/to/Verdana.ttf", fontname="Verdana"
    )
    
    # 3. It should have called clean_contents to remap font references.
    mock_clean.assert_called_once()


def test_normalize_pdf_no_subsets(sample_pdf_with_subset_font):
    """Test that a PDF with no subset fonts is returned unchanged."""
    # Create a PDF without any subset font names
    original_pdf = sample_pdf_with_subset_font.replace(b"AAAAAA+Verdana", b"Verdana")
    
    # Run the normalizer
    normalized_pdf = normalize_pdf_fonts(original_pdf)
    
    # The function should return the exact same bytes object if no changes are made.
    assert normalized_pdf is original_pdf
