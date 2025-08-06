import fitz
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from .fonts import find_font_path, normalize_pdf_fonts, SUBSET_FONT_RE

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
    print("\n--- Running create_test_pdf_with_subset_font ---")
    if doc.page_count == 0:
        doc.new_page()
    page = doc[0]

    font_buffer = fitz.Font("helv").buffer
    print(f"DEBUG: Inserting font with name '{font_name}'")
    page.insert_font(fontname=font_name, fontbuffer=font_buffer)
    print("DEBUG: Font inserted.")

    # We must use `insert_text` with `fontname` for this to work in a test context.
    # The TextWriter approach requires a valid `fitz.Font` object, which we can't create
    # for a font that is only defined within the page's resources.
    print("DEBUG: Inserting text with the custom font name.")
    page.insert_text((50, 72), text, fontname=font_name, fontsize=11)
    print("DEBUG: Text inserted.")
    return doc


def test_normalize_pdf_fonts_replaces_subset_font(mock_fontra, tmp_path):
    """Verify that a subset font is replaced with its full version."""
    mock_fontra.return_value = MagicMock(path=str(tmp_path / "Verdana.ttf"))
    (tmp_path / "Verdana.ttf").write_bytes(fitz.Font("helv").buffer)

    # Create a PDF with a subset font
    input_doc = fitz.open()
    input_doc = create_test_pdf_with_subset_font(input_doc)
    input_bytes = input_doc.tobytes()
    input_doc.close()

    # Normalize the PDF
    output_bytes = normalize_pdf_fonts(input_bytes)
    output_doc = fitz.open(stream=output_bytes, filetype="pdf")

    # Assertions
    mock_fontra.assert_called_once_with("Verdana", "Regular")
    found_fonts = {
        font[2].decode("utf-8", "ignore")
        for page in output_doc
        for font in page.get_fonts()
    }
    assert "Verdana" in found_fonts
    assert "ABCDEF+Verdana" not in found_fonts


def test_normalize_pdf_fonts_no_subsets():
    """Test that the PDF is unchanged if no subset fonts are present."""
    input_doc = fitz.open()
    page = input_doc.new_page()
    page.insert_text((50, 72), "Hello", fontname="helv")
    input_bytes = input_doc.tobytes()

    output_bytes = normalize_pdf_fonts(input_bytes)
    assert output_bytes == input_bytes


def test_normalize_pdf_fonts_font_not_found(mock_fontra):
    """Test that normalization is skipped for a font that cannot be found."""
    mock_fontra.return_value = None  # Mock fontra failing

    with patch("pathlib.Path.exists", return_value=False):  # Mock local fallback failing
        input_doc = fitz.open()
        input_doc = create_test_pdf_with_subset_font(
            input_doc, font_name="GHIJKL+NonExistentFont"
        )
        input_bytes = input_doc.tobytes()
        output_bytes = normalize_pdf_fonts(input_bytes)

        # The font should not have been replaced, original bytes returned
        assert input_bytes == output_bytes
        mock_fontra.assert_called_once_with("NonExistentFont", "Regular")


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
