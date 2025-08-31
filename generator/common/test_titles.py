"""Tests for title utilities."""

from generator.common.titles import generate_short_title


def test_generate_short_title_basic():
    """Test basic title shortening functionality."""
    # Test with no changes needed
    title = "Simple Title"
    result = generate_short_title(title)
    assert result == "Simple Title"


def test_generate_short_title_featuring_removal():
    """Test removal of featuring information."""
    # Test parentheses featuring
    title = "Song Title (feat. Artist Name)"
    result = generate_short_title(title)
    assert result == "Song Title"

    # Test bracket featuring
    title = "Song Title [featuring Artist Name]"
    result = generate_short_title(title)
    assert result == "Song Title"

    # Test case insensitive
    title = "Song Title (FEAT. Artist)"
    result = generate_short_title(title)
    assert result == "Song Title"


def test_generate_short_title_version_removal():
    """Test removal of version/edit information."""
    title = "Song Title (Radio Edit)"
    result = generate_short_title(title)
    assert result == "Song Title"

    title = "Song Title (Single Version)"
    result = generate_short_title(title)
    assert result == "Song Title"

    title = "Song Title (Mono Mix)"
    result = generate_short_title(title)
    assert result == "Song Title"


def test_generate_short_title_bracket_removal():
    """Test removal of bracketed information."""
    title = "Song Title [Some Info]"
    result = generate_short_title(title)
    assert result == "Song Title"


def test_generate_short_title_max_length():
    """Test title truncation with max length."""
    title = "This Is A Very Long Song Title That Should Be Truncated"
    result = generate_short_title(title, max_length=20)
    assert len(result) <= 20
    assert result.endswith("...")

    # Test truncation at word boundary
    title = "Short Title Here"
    result = generate_short_title(title, max_length=10)
    assert result == "Short T..."


def test_generate_short_title_wip_marker():
    """Test WIP marker functionality."""
    title = "Song Title"

    # Test with WIP marker enabled and ready to play
    result = generate_short_title(title, include_wip_marker=True, is_ready_to_play=True)
    assert result == "Song Title*"

    # Test with WIP marker enabled but not ready to play
    result = generate_short_title(
        title, include_wip_marker=True, is_ready_to_play=False
    )
    assert result == "Song Title"

    # Test with WIP marker disabled
    result = generate_short_title(
        title, include_wip_marker=False, is_ready_to_play=True
    )
    assert result == "Song Title"


def test_generate_short_title_complex():
    """Test complex title with multiple transformations."""
    title = "Very Long Song Title [Album Info] (feat. Another Artist) (Radio Edit)"
    result = generate_short_title(title, max_length=25)

    # Should remove bracketed info, featuring, and version info, then truncate
    assert len(result) <= 25
    assert "Album Info" not in result
    assert "feat." not in result
    assert "Radio Edit" not in result


def test_generate_short_title_whitespace_cleanup():
    """Test whitespace normalization."""
    title = "Song   Title    With   Extra   Spaces"
    result = generate_short_title(title)
    assert result == "Song Title With Extra Spaces"

    title = "  Leading and Trailing  "
    result = generate_short_title(title)
    assert result == "Leading and Trailing"


def test_generate_short_title_edge_cases():
    """Test edge cases."""
    # Empty string
    result = generate_short_title("")
    assert result == ""

    # Very short max length
    title = "Song"
    result = generate_short_title(title, max_length=2)
    assert result == "So"

    # Max length exactly equal to title length
    title = "Exact"
    result = generate_short_title(title, max_length=5)
    assert result == "Exact"
