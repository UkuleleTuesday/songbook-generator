"""Shared title utilities for songbook generation."""

import re


def generate_short_title(
    original_title: str,
    max_length: int = None,
    include_wip_marker: bool = False,
    is_ready_to_play: bool = False
) -> str:
    """
    Generate a shortened title using consistent heuristics.

    This function applies the same title shortening logic used in TOC generation
    to ensure consistency across the application.

    Args:
        original_title: The original song title
        max_length: Maximum allowed length for the title (optional)
        include_wip_marker: Whether to include WIP marker functionality
        is_ready_to_play: If True and include_wip_marker is True, appends '*'

    Returns:
        Shortened title that fits within max_length if specified
    """
    title = original_title.strip()

    # If max_length is specified and already short enough, continue with cleaning
    # for consistency, otherwise just clean

    # Remove featuring information in both parentheses and brackets
    # This regex matches parentheses or brackets containing feat./featuring
    title = re.sub(
        r"\s*[\(\[][^\)\]]*(?:feat\.|featuring)[^\)\]]*[\)\]]",
        "",
        title,
        flags=re.IGNORECASE,
    )

    # Remove bracketed information (after featuring removal to avoid conflicts)
    title = re.sub(r"\s*\[[^\]]*\]", "", title)

    # Remove version/edit information in parentheses
    # This regex matches specific keywords that indicate versions/edits
    title = re.sub(
        r"\s*\([^)]*(?:Radio|Single|Edit|Version|Mix|Remix|Mono)\b[^)]*\)",
        "",
        title,
        flags=re.IGNORECASE,
    )

    # Clean up any extra whitespace
    title = re.sub(r"\s+", " ", title).strip()

    # If max_length is specified and still too long, truncate with ellipsis
    if max_length is not None and len(title) > max_length:
        # Try to cut at a word boundary if possible
        if max_length > 3:
            truncate_length = max_length - 3  # Reserve space for "..."
            if " " in title[:truncate_length]:
                # Find the last space before the truncation point
                last_space = title[:truncate_length].rfind(" ")
                if (
                    last_space > max_length // 2
                ):  # Only use word boundary if it's not too short
                    title = title[:last_space] + "..."
                else:
                    title = title[:truncate_length] + "..."
            else:
                title = title[:truncate_length] + "..."
        else:
            title = title[:max_length]

    # Add WIP marker if requested
    if include_wip_marker and is_ready_to_play:
        title += "*"

    return title
