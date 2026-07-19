"""PDF output via WeasyPrint."""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from html import escape
from pathlib import Path

from src.images import download_images, replace_images_in_html

LOGGER = logging.getLogger("nextcloud-news-digest")

# HTML template for a single item
_ITEM_TEMPLATE = """\
<h2>{date}</h2>

<h3>{title}</h3>
<address>{meta}</address>
<div>{body}</div>

{link}
"""

_LINK_TEMPLATE = """\
<p><a href="{url}">{url}</a></p>
"""

_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
}


def _mime(path: Path) -> str:
    """Return MIME type for a file path by extension."""
    return _MIME_MAP.get(path.suffix.lower(), "application/octet-stream")


def _build_header_html(feed_name: str, folder_name: str, fetch_date: datetime) -> str:
    """Return HTML for the document header."""
    tz_name = fetch_date.tzname() or "UTC"
    ts = fetch_date.strftime("%Y-%m-%d %H:%M:%S")
    return f"""\
<h1>{escape(feed_name)}</h1>
<p><b>Folder:</b> {escape(folder_name)} &middot; <b>Fetch Date:</b> {ts} {escape(tz_name)}</p>
<hr>
"""


def _img_repl(m: re.Match, images_dir: Path) -> str:
    """Convert a markdown image link to an <img> tag with an embedded
    base64 data URI so the PDF is fully self-contained."""
    alt = m.group(1) or ""
    src = m.group(2)
    if src.startswith("images/") or src == "images":
        img_name = src.replace("images/", "")
        img_path = images_dir / img_name
        if img_path.exists():
            data = img_path.read_bytes()
            encoded = base64.b64encode(data).decode("ascii")
            mime = _mime(img_path)
            return f'<img src="data:{mime};base64,{encoded}" alt="{escape(alt)}" />'
    # External URL — keep as-is (WeasyPrint fetches it)
    return f'<img src="{escape(src)}" alt="{escape(alt)}" />'


def _html_from_content(
    content: list[dict],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
) -> str:
    """Convert the content list into an HTML document.

    Image processing::

        1. Download images from each item's raw ``body`` to
           ``output_dir/images/``.
        2. Replace ``<img>`` tags with markdown image links.
        3. Strip HTML tags (markdown image links survive).
        4. Convert markdown image links to base64 data-URI ``<img>``
           tags so WeasyPrint embeds them directly.

    Parameters
    ----------
    content : list[dict]
        Per-item content dicts.
    output_dir : Path
        Format output directory (images go to ``output_dir/images/``).

    Returns
    -------
    str
        Complete HTML document string.
    """
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_cache: dict[str, str] = {}

    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<title>" + escape(feed_name) + "</title>",
        "<style>",
        "body { font-family: sans-serif; max-width: 800px; margin: 2em auto; }",
        "h1 { border-bottom: 2px solid #333; }",
        "h2 { border-bottom: 1px solid #ccc; margin-top: 2em; }",
        "address { font-style: normal; color: #666; font-size: 0.9em; }",
        "div { margin: 0.5em 0; line-height: 1.5; }",
        "img { max-width: 100%; height: auto; }",
        "hr { border: none; border-top: 2px solid #333; margin: 2em 0; }",
        "a { color: #0366d6; }",
        "</style>",
        "</head>",
        "<body>",
        _build_header_html(feed_name, folder_name, fetch_date),
    ]

    for item in content:
        # Download images from raw body and convert to markdown links,
        # then strip HTML (preserving markdown image links).
        body_raw = item.get("body", "")
        if body_raw:
            image_refs = download_images(body_raw, output_dir, cache=image_cache)
            if image_refs:
                body_raw = replace_images_in_html(body_raw, image_refs)
                # Strip HTML tags, keeping markdown image links
                body_raw = re.sub(r"<[^>]+>", " ", body_raw)
                body_raw = re.sub(r"\s+", " ", body_raw).strip()

        # Convert markdown image links → HTML img tags (base64-embedded)
        body = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            lambda m: _img_repl(m, images_dir),
            body_raw,
        )
        # Convert anchor links back to HTML
        body = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            r'<a href="\2">\1</a>',
            body,
        )

        title = item.get("title", "Untitled")
        date_str = item.get("date_str", "")
        author = item.get("author", "")
        time_str = item.get("time_str", "")
        link = item.get("link", "")

        meta_parts: list[str] = []
        if author and author != "Unknown":
            meta_parts.append(escape(author))
        if date_str:
            meta_parts.append(escape(date_str))
        if time_str:
            meta_parts.append(escape(time_str))
        meta = " &middot; ".join(meta_parts)

        link_html = ""
        if link:
            link_html = _LINK_TEMPLATE.format(url=escape(link))

        item_html = _ITEM_TEMPLATE.format(
            title=escape(title),
            date=date_str,
            meta=meta,
            body=body,
            link=link_html,
        )
        html_parts.append(item_html)

    html_parts.append("</body>")
    html_parts.append("</html>")

    return "\n".join(html_parts)


def render(
    content: list[dict],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
) -> bytes:
    """Render a PDF document.

    Images are downloaded from the raw ``body`` field of each content
    item, and markdown image links in ``markdown_body`` are converted
    to base64 data-URI ``<img>`` tags so WeasyPrint embeds them
    directly in the PDF.

    Returns
    -------
    bytes
        The rendered PDF document.
    """
    from weasyprint import HTML

    html_str = _html_from_content(content, folder_name, feed_name, fetch_date, output_dir)
    return HTML(string=html_str).write_pdf()