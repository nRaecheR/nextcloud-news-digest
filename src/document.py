"""Markdown document generator for Open-Notebook import."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.images import download_images, replace_images_in_html

LOGGER = logging.getLogger("nextcloud-news-digest")


def _build_header(
    feed_name: str,
    folder_name: str,
    fetch_date: datetime,
    total_items: int,
    tz_name: str,
) -> list[str]:
    """Build the Markdown header shared by all output files."""
    lines: list[str] = []
    lines.append(f"# {feed_name}")
    lines.append("")
    lines.append(f"**Folder:** {folder_name}")
    lines.append(
        f"**Fetch Date:** {fetch_date.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}"
    )
    lines.append(f"**Total Items:** {total_items}")
    lines.append("")
    return lines


def _generate_lines(
    items: list[dict[str, Any]],
    image_cache: dict[str, str],
    output_dir: Path | None,
    strip_html: bool,
    max_content_len: int,
) -> list[str]:
    """Generate Markdown body lines for a subset of items.

    Parameters
    ----------
    items : list[dict]
        Already-sorted items (oldest-to-newest).
    image_cache : dict
        Shared URL-to-filename cache for deduplication.
    output_dir : Path | None
        Directory for image downloads.
    strip_html : bool
        If True, strip HTML from body content.
    max_content_len : int
        Maximum character length before truncation.

    Returns
    -------
    list[str]
        Markdown lines (without the shared header).
    """
    def strip_html_content(html: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    lines: list[str] = []

    if not items:
        lines.append("No new items found.")
        lines.append("")
        return lines

    # Group by date for readability
    current_date: str | None = None

    for item in items:
        pub_date_val = item.get("pubDate", 0)
        if pub_date_val and pub_date_val > 0:
            try:
                dt = datetime.fromtimestamp(int(pub_date_val))
            except (OSError, OverflowError, ValueError, TypeError):
                dt = datetime.now()
        else:
            dt = datetime.now()

        date_str = dt.strftime("%Y-%m-%d")

        if date_str != current_date:
            current_date = date_str
            lines.append("---")
            lines.append(f"## {date_str}")
            lines.append("")

        title = item.get("title", "Untitled")
        author = item.get("author", "")
        time_str = dt.strftime("%H:%M:%S")

        lines.append(f"### {title}")
        lines.append("")

        # Use body (full content from RSS) as the primary source.
        # Fall back to description if body is empty.
        body = item.get("body", "")
        desc = item.get("description", "")
        content = body or desc
        if content:
            # Download images from raw body before stripping HTML.
            if output_dir is not None:
                image_refs = download_images(
                    content, output_dir, cache=image_cache
                )
                if image_refs:
                    content = replace_images_in_html(content, image_refs)
                    LOGGER.info(
                        "Downloaded %d images in '%s'",
                        len(image_refs),
                        title[:50],
                    )

            if strip_html:
                content = strip_html_content(content)
            if len(content) > max_content_len:
                content = content[:max_content_len] + "(truncated)"
            lines.append(content)
            lines.append("")

        # Metadata row
        meta_parts: list[str] = []
        if author and author != "Unknown":
            meta_parts.append(f"Author: {author}")
        meta_parts.append(f"Date: {date_str}")
        meta_parts.append(f"Time: {time_str}")
        lines.append(f"*{' | '.join(meta_parts)}*")
        lines.append("")

        # Link if available
        link = item.get("url", "")
        if link:
            lines.append(f"[{link}]({link})")
            lines.append("")

    return lines


def generate_markdown(
    items: list[dict[str, Any]],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path | None = None,
) -> str:
    """Generate a Markdown document for Open-Notebook import.

    Items are sorted by ``pubDate`` timestamp (oldest-to-newest)
    regardless of input order.

    The output uses a structure Open-Notebook can parse:
    - Top-level ``#`` heading is the feed name (source title).
    - Items are grouped by date with ``##`` subheadings.
    - Each item gets a ``###`` heading with its title.
    - Metadata (author, date, time) is shown in an italic row.
    - Body content is HTML-stripped and truncated to 2000 characters.
      Uses ``body`` (full content) first, falls back to ``description``.
    - Links are included as markdown links.
    - Images are downloaded to ``output_dir/images/`` and referenced
      with relative markdown links (``![alt](images/file.jpg)``).

    Parameters
    ----------
    items : list[dict[str, Any]]
        News items already sorted oldest-to-newest.
    folder_name : str
        Name of the folder the feed belongs to.
    feed_name : str
        Name of the feed (used as the document heading).
    fetch_date : datetime
        When the fetch was performed (used for items without dates).
    output_dir : Path, optional
        Output directory path. If provided, images referenced in the body
        are downloaded to a subdirectory ``images/`` and replaced with
        relative markdown links.

    Returns
    -------
    str
        Complete Markdown document as a string.
    """
    # Resolve timezone from TZ env var (set by the container)
    tz_name = os.environ.get("TZ", "UTC").split("/")[-1]

    # Sort items by pubDate timestamp (oldest-to-newest)
    sorted_items = sorted(items, key=lambda x: int(x.get("pubDate", 0)))

    # Download images once, then share the cache across all items
    image_cache: dict[str, str] = {}
    if output_dir is not None:
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

    # Header
    header = _build_header(feed_name, folder_name, fetch_date, len(items), tz_name)

    # Body
    body = _generate_lines(
        sorted_items, image_cache, output_dir, strip_html=True, max_content_len=2000
    )

    return "\n".join(header + body)


def generate_markdown_files(
    items: list[dict[str, Any]],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
    days_per_file: int,
) -> list[str]:
    """Generate multiple Markdown files grouped by date range.

    Items are divided into time windows of ``days_per_file`` days each.
    Each file gets the same header with feed name, folder, fetch date,
    and total item count.  Image downloading is shared across all files
    so the same URL is only downloaded once.

    Parameters
    ----------
    items : list[dict[str, Any]]
        News items already sorted oldest-to-newest.
    folder_name : str
        Name of the folder the feed belongs to.
    feed_name : str
        Name of the feed (used as the document heading).
    fetch_date : datetime
        When the fetch was performed (used for items without dates).
    output_dir : Path
        Output directory path.  Images are written to ``output_dir/images/``.
    days_per_file : int
        Maximum number of calendar days per output file.

    Returns
    -------
    list[str]
        Paths to the generated files.
    """
    if days_per_file <= 0:
        days_per_file = 7

    tz_name = os.environ.get("TZ", "UTC").split("/")[-1]

    # Sort items by pubDate timestamp (oldest-to-newest)
    sorted_items = sorted(items, key=lambda x: int(x.get("pubDate", 0)))

    # Download images — cache is shared across all files
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_cache: dict[str, str] = {}

    if not sorted_items:
        path = output_dir / f"{folder_name}_{feed_name}_empty.md"
        content = "\n".join(
            _build_header(feed_name, folder_name, fetch_date, 0, tz_name)
            + ["No new items found.", ""]
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        LOGGER.info("No items — wrote empty file: %s", path)
        return [str(path)]

    # Determine date range from items
    item_dates: list[datetime] = []
    for item in sorted_items:
        pub_date_val = item.get("pubDate", 0)
        if pub_date_val and pub_date_val > 0:
            try:
                item_dates.append(datetime.fromtimestamp(int(pub_date_val)))
            except (OSError, OverflowError, ValueError, TypeError):
                continue

    if not item_dates:
        item_dates = [fetch_date]

    first_date = min(item_dates)
    last_date = max(item_dates)

    # Convert items to the format expected by _split_content_windows
    # (uses date_str instead of pubDate for consistent windowing)
    content_items: list[dict[str, Any]] = []
    for item in sorted_items:
        pub_date_val = item.get("pubDate", 0)
        if pub_date_val and pub_date_val > 0:
            try:
                dt = datetime.fromtimestamp(int(pub_date_val))
            except (OSError, OverflowError, ValueError, TypeError):
                dt = fetch_date
        else:
            dt = fetch_date
        content_items.append({
            **item,
            "date_str": dt.strftime("%Y-%m-%d"),
        })

    # Use shared splitter for consistent date windows
    windows = _split_content_windows(content_items, days_per_file)

    # Write each window
    file_paths: list[str] = []
    for window_index, window_items in enumerate(windows):
        path = _write_one_file(
            window_items,
            folder_name,
            feed_name,
            fetch_date,
            output_dir,
            image_cache,
            tz_name,
            window_index,
        )
        file_paths.append(path)

    return file_paths


def _split_content_windows(
    content: list[dict], days_per_file: int
) -> list[list[dict]]:
    """Split content list into date windows of *days_per_file* days each.

    Uses a sliding window: when an item falls at or beyond the window
    boundary, a new window starts from that item's date.

    Parameters
    ----------
    content : list[dict]
        Content dicts with a ``date_str`` field (YYYY-MM-DD).
    days_per_file : int
        Maximum number of calendar days per window.

    Returns
    -------
    list[list[dict]]
        List of content-window lists.
    """
    if days_per_file <= 1:
        return [content]

    window: timedelta = timedelta(days=days_per_file)
    windows: list[list[dict]] = [[]]
    current_start: datetime | None = None

    for item in content:
        date_str = item.get("date_str", "")
        if not date_str:
            continue
        try:
            item_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if current_start is None:
            current_start = item_dt
        if item_dt >= current_start + window:
            windows.append([])
            current_start = item_dt
        windows[-1].append(item)

    windows = [w for w in windows if w]
    return windows if windows else [[]]


def _write_one_file(
    items: list[dict[str, Any]],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
    image_cache: dict[str, str],
    tz_name: str,
    window_index: int,
) -> str:
    """Write a single Markdown file from a group of items."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = fetch_date.strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{folder_name}_{feed_name}_{ts}_p{window_index + 1:03d}.md"

    header = _build_header(feed_name, folder_name, fetch_date, len(items), tz_name)
    body = _generate_lines(
        items, image_cache, output_dir, strip_html=True, max_content_len=2000
    )
    content = "\n".join(header + body)
    path.write_text(content)

    return str(path)