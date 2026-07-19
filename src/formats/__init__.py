"""Output-format dispatch for the news fetcher.

Each format is a module under this package with a
``render()`` function::

    def render(
        content: list[dict],
        folder_name: str,
        feed_name: str,
        fetch_date: datetime,
        output_dir: Path,
    ) -> str:
        ...

where ``content`` is a list of per-item dicts with keys::

    {
        "title": str,
        "author": str,
        "date_str": str,       # YYYY-MM-DD (local time)
        "time_str": str,       # HH:MM:SS (local time)
        "html_body": str,      # raw HTML from the article
        "markdown_body": str,  # HTML-stripped / truncated body with image links
        "link": str,           # canonical URL (may be empty)
        "pubDate": int,        # Unix timestamp
    }

The ``render()`` function returns the full document as a string.
The caller decides the file extension based on the format name.

Known formats:
    md-inline – Markdown with base64-embedded images
    pdf       – PDF via WeasyPrint
    txt       – Plain text
    json      – Structured JSON
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("nextcloud-news-digest")


def _load_format_module(name: str) -> Any:
    """Lazy-import a format module by name."""
    if name == "md-inline":
        from src.formats import md_inline

        return md_inline
    if name == "pdf":
        from src.formats import pdf

        return pdf
    if name == "json":
        from src.formats import json_fmt

        return json_fmt
    if name == "txt":
        from src.formats import txt

        return txt
    return None


# Format name → file extension
_EXTENSION_MAP: dict[str, str] = {
    "md-inline": "md",
    "pdf": "pdf",
    "json": "json",
    "txt": "txt",
}

# Supported format names
_SUPPORTED = list(_EXTENSION_MAP.keys())


def render(
    format_name: str,
    content: list[dict],
    folder_name: str,
    feed_name: str,
    fetch_date: datetime,
    output_dir: Path,
) -> str:
    """Render *content* in the named format and return the document string.

    Parameters
    ----------
    format_name : str
        One of the known format keys (e.g. ``"pdf"``).
    content : list[dict]
        Per-item content dicts from the pipeline.
    folder_name : str
        Folder name for the document header.
    feed_name : str
        Feed name for the document heading.
    fetch_date : datetime
        When the fetch was performed.
    output_dir : Path
        Base output directory (each format writes to its own subdir).

    Returns
    -------
    str
        The rendered document content.

    Raises
    ------
    ValueError
        If *format_name* is not recognised.
    """
    module = _load_format_module(format_name)
    if module is None:
        raise ValueError(
            f"Unknown output format: {format_name!r}. "
            f"Supported: {', '.join(_SUPPORTED)}"
        )
    return module.render(
        content=content,
        folder_name=folder_name,
        feed_name=feed_name,
        fetch_date=fetch_date,
        output_dir=output_dir,
    )


def format_ext(format_name: str) -> str:
    """Return the file extension for a format name."""
    return _EXTENSION_MAP.get(format_name, format_name)


def supported_formats() -> list[str]:
    """Return a list of recognised format names."""
    return list(_SUPPORTED)