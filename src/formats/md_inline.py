"""Markdown with inline (base64-encoded) images."""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from pathlib import Path

from src.images import download_images, replace_images_in_html

LOGGER = logging.getLogger("nextcloud-news-digest")


def _build_header(folder_name: str, feed_name: str, fetch_date: datetime) -> str:
    """Return Markdown header lines."""
    tz_name = fetch_date.tzname() or "UTC"
    ts = fetch_date.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"# {feed_name}\n"
        f"\n"
        f"**Folder:** {folder_name}\n"
        f"**Fetch Date:** {ts} {tz_name}\n"
    )


def _image_repl(m: re.Match[str], images_dir: Path) -> str:
    """Replace a markdown image link with a base64 data URI."""
    alt = m.group(1) or ""
    src = m.group(2)

    # Only inline images that live under images_dir
    if src.startswith("images/") or src == "images":
        img_name = src.replace("images/", "")
        img_path = images_dir / img_name
        if img_path.exists():
            data = img_path.read_bytes()
            mime = _mime_from_path(img_path)
            encoded = base64.b64encode(data).decode("ascii")
            return f"![{alt}](data:{mime};base64,{encoded})"
    # Keep original if we can't inline it
    return m.group(0)


def _mime_from_path(path: Path) -> str:
    """Guess MIME type from file extension."""
    ext = path.suffix.lower()
    _MAP: dict[str, str] = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".avif": "image/avif",
        ".bmp": "image/bmp",
    }
    return _MAP.get(ext, "application/octet-stream")


def _build_item_lines(content: dict, images_dir: Path) -> list[str]:
    """Build one Markdown item block with inline images."""
    body = content.get("body", "")  # raw HTML for image processing
    markdown_body = content.get("markdown_body", "")  # pre-stripped text

    if body:
        # Download images from raw HTML and create markdown links
        image_refs = download_images(body, images_dir.parent, cache={})
        if image_refs:
            processed = replace_images_in_html(body, image_refs)
            LOGGER.info(
                "Downloaded %d images in '%s'",
                len(image_refs),
                content.get("title", "?")[:50],
            )
            # Strip HTML from processed body (now has markdown image links)
            markdown_body = re.sub(r"<[^>]+>", " ", processed)
            markdown_body = re.sub(r"\s+", " ", markdown_body).strip()
            markdown_body = markdown_body[:2000] if len(markdown_body) > 2000 else markdown_body
            if len(markdown_body) >= 2000 and body != markdown_body:
                markdown_body = markdown_body.rstrip() + " (truncated)"

    # Inline images: convert ![alt](images/file.jpg) → ![alt](data:...)
    if markdown_body:
        markdown_body = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            lambda m: _image_repl(m, images_dir),
            markdown_body,
        )

    title = content.get("title", "Untitled")
    date_str = content.get("date_str", "")
    time_str = content.get("time_str", "")
    author = content.get("author", "")
    link = content.get("link", "")

    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")

    if markdown_body:
        lines.append(markdown_body)
        lines.append("")

    # Metadata
    meta_parts: list[str] = []
    if author and author != "Unknown":
        meta_parts.append(f"Author: {author}")
    if date_str:
        meta_parts.append(f"Date: {date_str}")
    if time_str:
        meta_parts.append(f"Time: {time_str}")
    if meta_parts:
        lines.append(f"*{' | '.join(meta_parts)}*")
        lines.append("")

    # Link
    if link:
        lines.append(f"[{link}]({link})")
        lines.append("")

    return lines


def render(
    content: list[dict],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
) -> str:
    """Generate Markdown with all images embedded as base64 data URIs.

    Images are downloaded from the raw ``body`` field of each content
    item to ``output_dir/images/``, then converted to base64 data URIs.

    Returns
    -------
    str
        Complete Markdown document as a string.
    """
    images_dir = output_dir / "images"

    # Pre-download images to share cache across all items
    shared_cache: dict[str, str] = {}
    for item in content:
        body = item.get("body", "")
        if body:
            download_images(body, output_dir, cache=shared_cache)

    lines = [_build_header(folder_name, feed_name, fetch_date)]

    for item in content:
        item_lines = _build_item_lines(item, images_dir)
        lines.extend(item_lines)

    return "\n".join(lines)