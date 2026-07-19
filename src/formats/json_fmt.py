"""Structured JSON output."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.images import download_images, replace_images_in_html


def _build_item_dict(
    content: dict, images_dir: Path, cache: dict[str, str]
) -> dict:
    """Convert one content item dict to a serialisable structure."""
    body = content.get("body") or ""
    content_text = content.get("markdown_body") or ""

    if body:
        # Process body: download images, replace, strip HTML
        image_refs = download_images(body, images_dir, cache=cache)
        if image_refs:
            content_text = replace_images_in_html(body, image_refs)
        content_text = re.sub(r"<[^>]+>", " ", content_text)
        content_text = re.sub(r"\s+", " ", content_text).strip()
        content_text = content_text[:2000] if len(content_text) > 2000 else content_text
        if len(content_text) >= 2000 and body != content_text:
            content_text = content_text.rstrip() + " (truncated)"

    item: dict = {
        "title": content.get("title", "Untitled"),
        "author": content.get("author", ""),
        "date": content.get("date_str", ""),
        "time": content.get("time_str", ""),
        "content": content_text,
    }
    link = content.get("link", "")
    if link:
        item["url"] = link

    return item


def render(
    content: list[dict],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
) -> str:
    """Generate a structured JSON document.

    Images are downloaded from the raw ``body`` field of each content
    item to ``output_dir/images/`` and their alt text is included
    in the content field.

    Returns
    -------
    str
        JSON document as a string (pretty-printed).
    """

    images_dir = output_dir / "images"

    tz_name = fetch_date.tzname() or "UTC"

    # Shared cache (URL → filename)
    cache: dict[str, str] = {}

    document = {
        "feed": feed_name,
        "folder": folder_name,
        "fetch_date": fetch_date.isoformat(),
        "timezone": tz_name,
        "items": [
            _build_item_dict(item, images_dir, cache) for item in content
        ],
    }

    return json.dumps(document, indent=2, ensure_ascii=False)