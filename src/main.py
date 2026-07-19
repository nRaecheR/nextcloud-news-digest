#!/usr/bin/env python3
"""Fetch unread news from Nextcloud and generate output documents."""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.config import ConfigurationError, load_settings
from src.document import (
    generate_markdown,
    generate_markdown_files,
    _split_content_windows,
)
from src.formats import format_ext, render as render_format, supported_formats
from src.nextcloud_client import NextcloudNewsClient
from src.state import load_state, save_state  # used in file mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("nextcloud-news-digest")


def find_feed(
    client: NextcloudNewsClient, folder_name: str, feed_name: str
) -> tuple[int, str] | None:
    """Find a feed ID by searching folders then feeds.

    Parameters
    ----------
    client : NextcloudNewsClient
        Initialized API client.
    folder_name : str
        Folder to search.
    feed_name : str
        Feed name to match inside the folder.

    Returns
    -------
    tuple[int, str] | None
        (feed_id, feed_title) on success, or None if not found.
    """
    # Find the folder by title
    folder_id: int | None = None
    for folder in client.get_folders():
        if folder.get("title") == folder_name:
            folder_id = folder["id"]
            break

    if folder_id is None:
        LOGGER.warning("Folder '%s' not found.", folder_name)
        LOGGER.info("Available folders: %s", [
            f.get("title") for f in client.get_folders()
        ])
        return None

    # Find the feed inside the folder
    for feed in client.get_feeds():
        if feed.get("folderId") == folder_id and feed.get("title") == feed_name:
            return feed["id"], feed.get("title", feed_name)

    LOGGER.warning(
        "Feed '%s' not found in folder '%s'.", feed_name, folder_name
    )
    return None


def _build_content_items(
    items: list[dict],
) -> list[dict]:
    """Build per-item content dicts from raw news items.

    Computes derived fields (date, time, stripped body) but does **not**
    download images — image downloading is delegated to the renderer
    that needs them (markdown generator, PDF, md-inline, etc.).

    Parameters
    ----------
    items : list[dict]
        News items (already sorted).

    Returns
    -------
    list[dict]
        Content dicts for each item.

    Notes
    -----
    The ``body`` field contains the original raw HTML, kept for
    formatters that need to extract image URLs (e.g. PDF).
    The ``html_body`` field is the same raw HTML — used by the
    markdown generator which downloads images and converts
    ``<img>`` tags to markdown image links.
    """
    content: list[dict] = []

    for item in items:
        body = item.get("body") or ""

        # Strip HTML for plain-text / json consumers
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        text = text[:2000] if len(text) > 2000 else text
        if len(text) >= 2000 and body != text:
            text = text.rstrip() + " (truncated)"

        # Parse publication date
        pub_date_val = item.get("pubDate", 0)
        try:
            dt = datetime.fromtimestamp(int(pub_date_val)) if pub_date_val else datetime.now()
        except (OSError, OverflowError, ValueError, TypeError):
            dt = datetime.now()

        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        content.append({
            "title": item.get("title", "Untitled"),
            "author": item.get("author", ""),
            "date_str": date_str,
            "time_str": time_str,
            "html_body": body,
            "markdown_body": text,
            "link": item.get("url", ""),
            "pubDate": int(pub_date_val) if pub_date_val else 0,
            "body": body,  # raw HTML for image extraction (PDF, etc.)
        })

    return content






def _write_output(
    output_dir: Path,
    filename_prefix: str,
    content: list[dict],
    formats: list[str],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    days_per_file: int,
) -> list[str]:
    """Write all requested output formats.

    Parameters
    ----------
    output_dir : Path
        Base output directory (e.g. ``/output``).
    filename_prefix : str
        Timestamp prefix (e.g. ``news_20260718_082315``).
    content : list[dict]
        Per-item content dicts.
    formats : list[str]
        Format names to generate (e.g. ``["md", "pdf"]``).
    folder_name : str
        Folder name for headers.
    feed_name : str
        Feed name for headers.
    fetch_date : datetime
        When the fetch was performed.
    days_per_file : int
        Split markdown and PDF output into date windows.

    Returns
    -------
    list[str]
        Paths to the generated files.
    """
    generated_paths: list[str] = []

    for fmt in formats:
        fmt_dir = output_dir / fmt
        fmt_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "md":
            # Markdown — multi-file with date windows
            if days_per_file > 1:
                paths = generate_markdown_files(
                    [
                        {
                            "title": c["title"],
                            "author": c["author"],
                            "pubDate": c["pubDate"],
                            "body": c["html_body"],
                            "description": c["markdown_body"],
                            "url": c["link"],
                        }
                        for c in content
                    ],
                    folder_name,
                    feed_name,
                    fetch_date,
                    output_dir=fmt_dir,
                    days_per_file=days_per_file,
                )
                generated_paths.extend(paths)
            else:
                md_content = generate_markdown(
                    [
                        {
                            "title": c["title"],
                            "author": c["author"],
                            "pubDate": c["pubDate"],
                            "body": c["html_body"],
                            "description": c["markdown_body"],
                            "url": c["link"],
                        }
                        for c in content
                    ],
                    folder_name,
                    feed_name,
                    fetch_date,
                    output_dir=fmt_dir,
                )
                path = fmt_dir / f"{filename_prefix}.md"
                path.write_text(md_content)
                generated_paths.append(str(path))

        elif fmt == "md-inline":
            # md-inline — images embedded as base64; renderer handles downloads
            doc_bytes = render_format(
                format_name=fmt,
                content=content,
                folder_name=folder_name,
                feed_name=feed_name,
                fetch_date=fetch_date,
                output_dir=fmt_dir,
            )
            ext = format_ext(fmt)
            path = fmt_dir / f"{filename_prefix}.{ext}"

            if isinstance(doc_bytes, bytes):
                path.write_bytes(doc_bytes)
            else:
                path.write_text(doc_bytes)
            generated_paths.append(str(path))

            # Clean up temporary image cache (md-inline embeds images as base64)
            tmp_images = fmt_dir / "images"
            if tmp_images.is_dir():
                for f in tmp_images.iterdir():
                    f.unlink()
                tmp_images.rmdir()

        elif fmt == "pdf":
            # PDF — respect DAYS_PER_FILE by splitting into windows
            windowed_content = _split_content_windows(content, days_per_file)
            if len(windowed_content) > 1:
                LOGGER.info(
                    "Splitting PDF into %d date window(s) (DAYS_PER_FILE=%d)",
                    len(windowed_content),
                    days_per_file,
                )
            # Download images once for all windows (shared cache)
            all_images_cache: dict[str, str] = {}
            for window_idx, window_items in enumerate(windowed_content):
                suffix = f"_p{window_idx + 1:03d}" if len(windowed_content) > 1 else ""
                path = fmt_dir / f"{filename_prefix}{suffix}.pdf"
                pdf_bytes = render_format(
                    format_name="pdf",
                    content=window_items,
                    folder_name=folder_name,
                    feed_name=feed_name,
                    fetch_date=fetch_date,
                    output_dir=fmt_dir,
                )
                path.write_bytes(pdf_bytes)
                generated_paths.append(str(path))

            # Clean up temporary image cache (PDF embeds images as base64)
            tmp_images = fmt_dir / "images"
            if tmp_images.is_dir():
                for f in tmp_images.iterdir():
                    f.unlink()
                tmp_images.rmdir()

        elif fmt in supported_formats():
            # txt, json — render once (no images needed)
            doc_bytes = render_format(
                format_name=fmt,
                content=content,
                folder_name=folder_name,
                feed_name=feed_name,
                fetch_date=fetch_date,
                output_dir=fmt_dir,
            )
            ext = format_ext(fmt)
            path = fmt_dir / f"{filename_prefix}.{ext}"

            if isinstance(doc_bytes, bytes):
                path.write_bytes(doc_bytes)
            else:
                path.write_text(doc_bytes)
            generated_paths.append(str(path))

        else:
            LOGGER.warning("Unsupported format: %s — skipped.", fmt)

    return generated_paths


def _mark_items_read(client: NextcloudNewsClient, items: list[dict]) -> None:
    """Mark all fetched items as read on the server.

    Uses the batch endpoint for efficiency. Errors are logged but
    do not abort — the run has already produced output.

    Parameters
    ----------
    client : NextcloudNewsClient
        Initialized API client.
    items : list[dict]
        News items to mark as read.
    """
    item_ids = [item["id"] for item in items if "id" in item]
    if not item_ids:
        return

    try:
        client.mark_items_read_batch(item_ids)
        LOGGER.info("Marked %d item(s) as read.", len(item_ids))
    except Exception as exc:
        LOGGER.warning("Failed to mark items as read: %s", exc)


def _run_pipeline(
    items: list[dict],
    settings: "Settings",
    feed_title: str,
    post_fetch_callback: Callable[[], None],
) -> int:
    """Execute the common fetch pipeline (sort, build, write, log).

    Parameters
    ----------
    items : list[dict]
        News items (will be sorted in-place).
    settings : Settings
        Application settings.
    feed_title : str
        Feed title for output headers.
    post_fetch_callback : callable
        Mode-specific action (save_state, _mark_items_read, or no-op).

    Returns
    -------
    int
        Exit code (0 on success).
    """
    items.sort(key=lambda x: int(x.get("pubDate", 0)))

    now = datetime.now()
    output_dir = Path("/output")
    content = _build_content_items(items)

    filename_prefix = f"{settings.news_folder}_{feed_title}_{now.strftime('%Y%m%d_%H%M%S')}"

    generated_paths = _write_output(
        output_dir=output_dir,
        filename_prefix=filename_prefix,
        content=content,
        formats=settings.output_formats,
        folder_name=settings.news_folder,
        feed_name=feed_title,
        fetch_date=now,
        days_per_file=settings.days_per_file,
    )

    LOGGER.info("Documents written to: %s", generated_paths)
    LOGGER.info("Generated %d file(s) (%d items)", len(generated_paths), len(content))

    # Post-fetch action (mode-dependent)
    post_fetch_callback()

    LOGGER.info("Done. %d items processed.", len(items))
    return 0


def main() -> int:
    """Main entry point. Returns 0 on success, 1 on error."""
    # 1. Load configuration
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 1

    LOGGER.info("Base URL: %s", settings.base_url)
    LOGGER.info("Folder: %s", settings.news_folder)
    LOGGER.info("Feed: %s", settings.news_feed)
    LOGGER.info("Output formats: %s", ", ".join(settings.output_formats))
    LOGGER.info("State mode: %s", settings.state_mode)

    # 2. Initialize the Nextcloud API client
    try:
        client = NextcloudNewsClient(
            base_url=settings.base_url,
            user=settings.user,
            access_token=settings.access_token,
            timeout_seconds=settings.timeout_seconds,
        )
    except Exception as exc:
        LOGGER.error("Failed to initialize Nextcloud client: %s", exc)
        return 1

    # 3. Find the feed by name
    feed_info = find_feed(client, settings.news_folder, settings.news_feed)
    if feed_info is None:
        LOGGER.error("Could not locate feed. Exiting.")
        return 1

    feed_id, feed_title = feed_info
    LOGGER.info("Found feed ID %d: %s", feed_id, feed_title)

    # 4. Fetch items (mode-dependent strategy)
    if settings.state_mode == "none":
        # Always fetch all unread items, no state tracking
        LOGGER.info("State mode=none: fetching all unread items.")
        items, _ = client.get_feed_items(feed_id, last_modified=0)
        if not items:
            LOGGER.info("No unread items to process.")
            return 0

        # Common pipeline
        return _run_pipeline(
            items=items,
            settings=settings,
            feed_title=feed_title,
            post_fetch_callback=lambda: None,
        )

    elif settings.state_mode == "file":
        # Load/save timestamp from file (legacy behavior)
        state = load_state(settings.state_file)
        last_timestamp = state.get("last_fetched_timestamp", 0)
        if last_timestamp:
            LOGGER.info("Resuming from timestamp %d", last_timestamp)
        else:
            LOGGER.info("No previous state found. Fetching all unread items.")
        items, new_timestamp = client.get_feed_items(
            feed_id, last_modified=last_timestamp
        )

        if not items:
            LOGGER.info("No unread items to process.")
            save_state(settings.state_file, new_timestamp)
            return 0

        # Common pipeline
        return _run_pipeline(
            items=items,
            settings=settings,
            feed_title=feed_title,
            post_fetch_callback=lambda: save_state(settings.state_file, new_timestamp),
        )

    else:  # state_mode == "mark_read"
        # Fetch all unread items, mark them as read after processing
        LOGGER.info("State mode=mark_read: fetching all unread items, will mark as read.")
        items, _ = client.get_feed_items(feed_id, last_modified=0)

        if not items:
            LOGGER.info("No unread items to process.")
            return 0

        # Common pipeline
        return _run_pipeline(
            items=items,
            settings=settings,
            feed_title=feed_title,
            post_fetch_callback=lambda: _mark_items_read(client, items),
        )


if __name__ == "__main__":
    sys.exit(main())