from toc import resolve_font, DEFAULT_FONT, load_toc_config, generate_toc_title


def test_resolve_font_valid_fontfile(mocker):
    # Mock fitz.Font to simulate successful font loading
    mock_font = mocker.patch("fitz.Font")
    fontfile = "valid_font.ttf"
    result = resolve_font(fontfile, DEFAULT_FONT)
    assert result == fontfile
    mock_font.assert_called_once_with(fontfile=fontfile)


def test_resolve_font_invalid_fontfile(mocker):
    # Mock fitz.Font to simulate font loading failure
    mock_font = mocker.patch("fitz.Font", side_effect=Exception("Invalid font"))
    fontfile = "invalid_font.ttf"
    result = resolve_font(fontfile, DEFAULT_FONT)
    assert result == DEFAULT_FONT
    mock_font.assert_called_once_with(fontfile=fontfile)


def test_resolve_font_no_fontfile(mocker):
    # Test with no fontfile provided
    mock_font = mocker.patch("fitz.Font")
    result = resolve_font(None, DEFAULT_FONT)
    assert result == DEFAULT_FONT
    mock_font.assert_not_called()


def test_load_toc_config_with_existing_file_but_invalid_font(mocker):
    mock_config = {
        "toc": {
            "text-font": "custom-font",
            "text-fontsize": 12,
            "title-font": "custom-title-font",
            "title-fontsize": 18,
        }
    }
    mock_load_config = mocker.patch("toc.load_config", return_value=mock_config)
    config = load_toc_config()
    assert config.text_font == DEFAULT_FONT
    assert config.text_fontsize == 12
    assert config.title_font == DEFAULT_FONT
    assert config.title_fontsize == 18
    mock_load_config.assert_called_once()


def test_load_toc_config_with_missing_file(mocker):
    mock_load_config = mocker.patch("toc.load_config", return_value={})
    config = load_toc_config()
    assert config.text_font == DEFAULT_FONT
    assert config.text_fontsize == 9
    assert config.title_font == DEFAULT_FONT
    assert config.title_fontsize == 16
    mock_load_config.assert_called_once()


def test_load_toc_config_partial_override(mocker):
    mock_config = {
        "toc": {
            "text-fontsize": 14,
        }
    }
    mock_load_config = mocker.patch("toc.load_config", return_value=mock_config)
    config = load_toc_config()
    assert config.text_font == DEFAULT_FONT
    assert config.text_fontsize == 14
    assert config.title_font == DEFAULT_FONT
    assert config.title_fontsize == 16
    mock_load_config.assert_called_once()


def test_generate_toc_title_short_enough():
    """Test that short titles are returned unchanged."""
    title = "Short Title"
    result = generate_toc_title(title, max_length=60)
    assert result == "Short Title"


def test_generate_toc_title_truncate_with_ellipsis():
    """Test truncation with ellipsis when still too long."""
    title = "This is a very long song title that should be truncated"
    result = generate_toc_title(title, max_length=30)
    assert "..." in result
    assert len(result) <= 30


def test_generate_toc_title_preserves_important_parentheses():
    """Test that important parentheses in titles are preserved."""
    # From the TOC - parentheses that are part of the actual title
    title = "(Don't Fear) The Reaper - Blue Öyster Cult" 
    result = generate_toc_title(title, max_length=60)
    assert result == "(Don't Fear) The Reaper - Blue Öyster Cult"


def test_generate_toc_title_preserves_artist_hyphen():
    """Test that artist separation with hyphen is preserved."""
    title = "Song Title - Artist Name"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title - Artist Name"


def test_generate_toc_title_strips_whitespace():
    """Test that leading and trailing whitespace is stripped."""
    title = "  Song Title  "
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_empty_string():
    """Test with empty string."""
    title = ""
    result = generate_toc_title(title, max_length=60)
    assert result == ""


def test_generate_toc_title_very_short_max_length():
    """Test with very short max length."""
    title = "Long Title"
    result = generate_toc_title(title, max_length=3)
    assert len(result) == 3


def test_generate_toc_title_basic_functionality():
    """Test basic functionality with realistic examples."""
    # Test that the function works for basic cases
    title = "Simple Song Title - Artist"
    result = generate_toc_title(title, max_length=60)
    assert result == "Simple Song Title - Artist"
    
    # Test truncation
    long_title = "This is an extremely long song title that definitely exceeds our limit"
    result = generate_toc_title(long_title, max_length=20)
    assert len(result) <= 20
    assert "..." in result
