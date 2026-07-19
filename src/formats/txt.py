"""Plain text output."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.images import download_images, replace_images_in_html


def _build_header(folder_name: str, feed_name: str, fetch_date: datetime) -> str:
    """Return plain text header."""
    tz_name = fetch_date.tzname() or "UTC"
    ts = fetch_date.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"{feed_name}\n"
        f"{'=' * len(feed_name)}\n"
        f"\n"
        f"Folder: {folder_name}\n"
        f"Fetch Date: {ts} {tz_name}\n"
    )


def _build_item_lines(
    content: dict, images_dir: Path, cache: dict[str, str]
) -> list[str]:
    """Build one plain text item block."""
    body = content.get("body", "")  # raw HTML
    markdown_body = content.get("markdown_body", "")  # pre-stripped text

    if body:
        image_refs = download_images(body, images_dir, cache=cache)
        if image_refs:
            markdown_body = replace_images_in_html(body, image_refs)

    # Strip HTML for plain text
    text = re.sub(r"<[^>]+>", " ", markdown_body)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:2000] if len(text) > 2000 else text
    if len(text) >= 2000 and markdown_body != text:
        text = text.rstrip() + " (truncated)"

    title = content.get("title", "Untitled")
    date_str = content.get("date_str", "")
    time_str = content.get("time_str", "")
    author = content.get("author", "")
    link = content.get("link", "")

    lines: list[str] = []
    lines.append(f"\n{title}")
    lines.append(f"{'-' * len(title)}")

    meta_parts: list[str] = []
    if author and author != "Unknown":
        meta_parts.append(f"Author: {author}")
    if date_str:
        meta_parts.append(f"Date: {date_str}")
    if time_str:
        meta_parts.append(f"Time: {time_str}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    if text:
        lines.append("")
        lines.append(text)

    if link:
        lines.append("")
        lines.append(link)

    return lines


def render(
    content: list[dict],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
) -> str:
    """Generate a plain text document.

    Images are downloaded from the raw ``body`` field of each content
    item to ``output_dir/images/`` and their alt text is preserved
    in the plain text output.

    Returns
    -------
    str
        Complete plain text document as a string.
    """
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Shared cache across all items (URL → filename)
    cache: dict[str, str] = {}

    lines = [_build_header(folder_name, feed_name, fetch_date)]

    for item in content:
        item_lines = _build_item_lines(item, images_dir, cache)
        lines.extend(item_lines)

    return "\n".join(lines)