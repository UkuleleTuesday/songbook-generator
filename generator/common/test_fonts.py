import importlib.resources

import fitz
import pytest
from unittest.mock import patch, MagicMock

from .fonts import (
    _gather_font_replacements,
    find_font_path,
    normalize_pdf_fonts,
    resolve_font,
    SUBSET_FONT_RE,
)

# A minimal valid PDF with one page.
MINIMAL_PDF_BYTES = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000059 00000 n \n0000000112 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF"


@pytest.fixture(autouse=True)
def mock_fontra(mocker):
    """Mocks fontra to prevent it from actually scanning the system."""
    mocker.patch("fontra.init_fontdb")
    mock_get = mocker.patch("fontra.get_font")
    return mock_get


def test_find_font_path_fontra_success(mock_fontra):
    """Test that fontra finding a font works."""
    mock_fontra.return_value = MagicMock(path="/system/fonts/Verdana.ttf")
    assert find_font_path("Verdana-Regular") == "/system/fonts/Verdana.ttf"
    mock_fontra.assert_called_once_with("Verdana", "Regular")


def test_find_font_path_fontra_fails_fallback_succeeds(mock_fontra, tmp_path):
    """Test fallback to local fonts directory when fontra fails."""
    mock_fontra.return_value = None  # fontra doesn't find the font
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    (fonts_dir / "Arial-Bold.ttf").touch()

    with patch("generator.common.fonts.FONTS_DIR", fonts_dir):
        assert find_font_path("Arial-Bold") == str(fonts_dir / "Arial-Bold.ttf")
    mock_fontra.assert_called_once_with("Arial", "Bold")


def test_find_font_path_not_found(mock_fontra, tmp_path):
    """Test that None is returned when font is not found anywhere."""
    mock_fontra.return_value = None
    with patch("generator.common.fonts.FONTS_DIR", tmp_path / "nonexistent"):
        assert find_font_path("NonExistentFont-Whatever") is None
    mock_fontra.assert_called_once_with("NonExistentFont", "Whatever")


def create_test_pdf_with_subset_font(
    doc, font_name="ABCDEF+Verdana", text="Hello"
) -> fitz.Document:
    """Helper to create a PDF with a subset-like font name."""
    if doc.page_count == 0:
        doc.new_page()
    page = doc[0]

    font_buffer = fitz.Font("helv").buffer
    # Inserting the font and then using it in insert_text is the key to get it
    # correctly listed in the page's fonts.
    page.insert_font(fontname=font_name, fontbuffer=font_buffer, set_simple=True)
    page.insert_text((50, 72), text, fontname=font_name, fontsize=11)
    return doc


# --- Tests for _gather_font_replacements ---


def test_gather_font_replacements_identifies_subsets(mock_fontra, tmp_path):
    """Test that subset fonts are correctly identified and prepared for replacement."""
    mock_fontra.return_value = MagicMock(path=str(tmp_path / "Verdana.ttf"))
    (tmp_path / "Verdana.ttf").write_bytes(fitz.Font("helv").buffer)

    doc = fitz.open()
    doc = create_test_pdf_with_subset_font(doc)
    fonts_on_page = doc[0].get_fonts(full=True)
    original_xref = next(f[0] for f in fonts_on_page if "ABCDEF+" in f[3])

    font_xref_map, embedded_fonts = _gather_font_replacements(doc)

    assert original_xref in font_xref_map
    assert "Verdana" in embedded_fonts
    assert len(font_xref_map) == 1
    assert len(embedded_fonts) == 1
    mock_fontra.assert_called_once_with("Verdana", "Regular")


def test_gather_font_replacements_no_subsets():
    """Test that no replacements are gathered when there are no subset fonts."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Hello", fontname="helv")

    font_xref_map, embedded_fonts = _gather_font_replacements(doc)
    assert not font_xref_map
    assert not embedded_fonts


def test_gather_font_replacements_font_not_found(mock_fontra):
    """Test that a subset font is skipped if its full font file is not found."""
    mock_fontra.return_value = None
    doc = fitz.open()
    doc = create_test_pdf_with_subset_font(doc, font_name="GHIJKL+NonExistentFont")

    font_xref_map, embedded_fonts = _gather_font_replacements(doc)
    assert not font_xref_map
    assert not embedded_fonts
    mock_fontra.assert_called_once_with("NonExistentFont", "Regular")


# --- Tests for normalize_pdf_fonts ---


@patch("generator.common.fonts._gather_font_replacements")
def test_normalize_pdf_fonts_replaces_subset_font(mock_gatherer, mock_fontra, tmp_path):
    """Verify that a subset font is replaced with its full version."""
    # We test _gather_font_replacements separately, so here we mock its behavior.
    # We need a real doc to perform the final replacement steps on.
    doc = fitz.open()
    doc = create_test_pdf_with_subset_font(doc)
    fonts_on_page = doc[0].get_fonts(full=True)
    original_xref = next(f[0] for f in fonts_on_page if "ABCDEF+" in f[3])

    # Simulate that _gather_font_replacements found a replacement and embedded a new font.
    # The new_xref would be created by `page.insert_font` inside the real function.
    # For the test, we can just grab an existing object's xref.
    new_xref = 1  # A valid xref in a minimal PDF
    mock_gatherer.return_value = ({original_xref: new_xref}, {"Verdana": new_xref})

    input_bytes = doc.tobytes()
    doc.close()

    # Normalize the PDF
    output_bytes = normalize_pdf_fonts(input_bytes)
    output_doc = fitz.open(stream=output_bytes, filetype="pdf")

    # Assertions
    mock_gatherer.assert_called_once()
    # Check that the object at original_xref now points to new_xref
    assert output_doc.xref_object(original_xref) == f"{new_xref} 0 R"


def test_normalize_pdf_fonts_no_subsets():
    """Test that the PDF is unchanged if no subset fonts are present."""
    input_doc = fitz.open()
    page = input_doc.new_page()
    page.insert_text((50, 72), "Hello", fontname="helv")
    input_bytes = input_doc.tobytes()

    output_bytes = normalize_pdf_fonts(input_bytes)
    assert output_bytes == input_bytes


@patch("generator.common.fonts._gather_font_replacements", return_value=({}, {}))
def test_normalize_pdf_fonts_font_not_found(mock_gatherer, mock_fontra):
    """Test that normalization is skipped for a font that cannot be found."""
    input_doc = fitz.open()
    input_doc = create_test_pdf_with_subset_font(
        input_doc, font_name="GHIJKL+NonExistentFont"
    )
    input_bytes = input_doc.tobytes()
    output_bytes = normalize_pdf_fonts(input_bytes)

    # The font should not have been replaced, original bytes returned
    assert input_bytes == output_bytes
    mock_gatherer.assert_called_once()




@pytest.mark.parametrize(
    "name, expected_base",
    [
        ("ABCDEF+Verdana-Bold", "Verdana-Bold"),
        ("GHIJKL+Arial", "Arial"),
        ("NotASubset", None),
    ],
)
def test_subset_font_re(name, expected_base):
    """Test the regex for identifying subset fonts."""
    match = SUBSET_FONT_RE.match(name)
    if expected_base:
        assert match and match.group(1) == expected_base
    else:
        assert not match


def test_normalize_pdf_fonts_empty_pdf():
    """Test that an empty/invalid PDF is returned as is."""
    with pytest.raises(fitz.EmptyFileError):
        normalize_pdf_fonts(b"")
    assert normalize_pdf_fonts(MINIMAL_PDF_BYTES) == MINIMAL_PDF_BYTES


# --- Tests for resolve_font ---


@patch("generator.common.fonts.find_font_path")
@patch("importlib.resources.files")
@patch("fitz.Font")
def test_resolve_font_from_package_resources(
    mock_fitz_font, mock_importlib_files, mock_find_font_path
):
    """Test that a font is loaded from package resources if available."""
    # Setup mock for importlib.resources
    mock_font_file = MagicMock()
    mock_font_file.read_bytes.return_value = b"font_data"
    mock_importlib_files.return_value.joinpath.return_value = mock_font_file

    resolve_font("SomeFont.ttf")

    mock_importlib_files.assert_called_once_with("generator.fonts")
    mock_importlib_files.return_value.joinpath.assert_called_once_with("SomeFont.ttf")
    mock_fitz_font.assert_called_once_with(fontbuffer=b"font_data")
    mock_find_font_path.assert_not_called()


@patch("generator.common.fonts.find_font_path")
@patch("importlib.resources.files", side_effect=FileNotFoundError)
@patch("fitz.Font")
def test_resolve_font_from_system_path(
    mock_fitz_font, mock_importlib_files, mock_find_font_path
):
    """Test that a font is loaded from a system path when not in resources."""
    mock_find_font_path.return_value = "/fake/path/to/font.ttf"

    resolve_font("SomeFont.ttf")

    mock_find_font_path.assert_called_once_with("SomeFont.ttf")
    mock_fitz_font.assert_called_once_with(fontfile="/fake/path/to/font.ttf")


@patch("generator.common.fonts.find_font_path", return_value=None)
@patch("importlib.resources.files", side_effect=FileNotFoundError)
@patch("fitz.Font")
def test_resolve_font_fallback_to_fitz_search(
    mock_fitz_font, mock_importlib_files, mock_find_font_path
):
    """Test that it falls back to fitz's built-in search."""
    resolve_font("SomeFont-Bold")

    mock_fitz_font.assert_called_once_with("SomeFont-Bold")


@patch("generator.common.fonts.find_font_path", return_value=None)
@patch("importlib.resources.files", side_effect=FileNotFoundError)
def test_resolve_font_total_failure(mock_importlib_files, mock_find_font_path):
    """Test that it falls back to built-in 'helv' when all methods fail."""
    original_fitz_font = fitz.Font

    def fitz_font_side_effect(font_name, *args, **kwargs):
        if font_name == "NonExistentFont":
            raise RuntimeError("Font not found")
        # For the fallback 'helv', we need to return a real font to check its properties
        return original_fitz_font(font_name, *args, **kwargs)

    with patch("fitz.Font", side_effect=fitz_font_side_effect) as mock_fitz_font:
        font = resolve_font("NonExistentFont")

        # After all attempts fail, it should return a fitz.Font object for "helv"
        assert isinstance(font, original_fitz_font)
        assert "helv" in font.name.lower()
        # Verify that fitz.Font was called first for the original font, then for the fallback.
        assert mock_fitz_font.call_count == 2
        mock_fitz_font.assert_any_call("NonExistentFont")
        mock_fitz_font.assert_any_call("helv")
