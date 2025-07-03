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


def test_generate_toc_title_removes_feat():
    """Test removal of featuring information."""
    title = "Song Title (feat. Artist Name)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_radio_edit():
    """Test removal of radio edit information."""
    title = "Song Title (Radio Edit)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_single_version():
    """Test removal of single version information."""
    title = "Song Title (Single Version)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_version():
    """Test removal of version information."""
    title = "Song Title (Version 2.0)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_mix():
    """Test removal of mix information."""
    title = "Song Title (Extended Mix)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_remix():
    """Test removal of remix information."""
    title = "Song Title (Remix)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_case_insensitive():
    """Test that removal is case insensitive."""
    title = "Song Title (FEAT. Artist Name)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_other_parentheses():
    """Test removal of other parenthetical information at the end."""
    title = "Song Title (2023)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_removes_brackets():
    """Test removal of bracketed information."""
    title = "Song Title [Alternative Version]"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_multiple_parentheses():
    """Test with multiple parenthetical elements."""
    title = "Song Title (feat. Artist) (Radio Edit)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_cleans_whitespace():
    """Test that extra whitespace is cleaned up."""
    title = "Song   Title    (feat. Artist)"
    result = generate_toc_title(title, max_length=60)
    assert result == "Song Title"


def test_generate_toc_title_truncate_with_ellipsis():
    """Test truncation with ellipsis when still too long."""
    title = "This is a very long song title that should be truncated"
    result = generate_toc_title(title, max_length=30)
    assert result == "This is a very long song..."
    assert len(result) == 30


def test_generate_toc_title_truncate_at_word_boundary():
    """Test truncation at word boundary when possible."""
    title = "This is a moderately long song title"
    result = generate_toc_title(title, max_length=25)
    assert result == "This is a moderately..."
    assert len(result) <= 25


def test_generate_toc_title_truncate_no_word_boundary():
    """Test truncation without word boundary when no good break point."""
    title = "Verylongwordwithoutspaces"
    result = generate_toc_title(title, max_length=15)
    assert result == "Verylongwor..."
    assert len(result) == 15


def test_generate_toc_title_very_short_max_length():
    """Test with very short max length."""
    title = "Long Title"
    result = generate_toc_title(title, max_length=3)
    assert result == "Lon"
    assert len(result) == 3


def test_generate_toc_title_real_world_examples():
    """Test with real examples from the TOC."""
    # Test a long title with featuring
    title = "Get Lucky (Radio Edit) [feat. Pharrell Williams, Nile Rodgers] - Daft Punk"
    result = generate_toc_title(title, max_length=50)
    expected = "Get Lucky - Daft Punk"
    assert result == expected

    # Test another real example
    title = "Valerie (feat. Amy Winehouse) (Version Revisited) - Mark Ronson"
    result = generate_toc_title(title, max_length=50)
    expected = "Valerie - Mark Ronson"
    assert result == expected


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


def test_generate_toc_title_only_parentheses():
    """Test with title that's only parentheses."""
    title = "(feat. Artist)"
    result = generate_toc_title(title, max_length=60)
    assert result == ""


def test_generate_toc_title_parentheses_in_middle():
    """Test that parentheses in the middle are not removed by the end-anchored regex."""
    title = "Song (Part 1) Title"
    result = generate_toc_title(title, max_length=60)
    # Should only remove version-related parentheses, not ones in the middle
    assert result == "Song (Part 1) Title"
