import importlib.resources

import fitz
import pytest
from unittest.mock import patch, MagicMock

from .fonts import (
    find_font_path,
    resolve_font,
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
