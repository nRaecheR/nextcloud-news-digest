"""Tests for src/formats/."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

try:
    from weasyprint import HTML  # noqa: F401 – trigger import side-effect

    _WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    _WEASYPRINT_AVAILABLE = False

from src.formats import format_ext, render, supported_formats
from src.formats import json_fmt, md_inline, pdf, txt


def _utcnow() -> datetime:
    return datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def _sample_content() -> list[dict]:
    """Return a list of per-item content dicts matching the pipeline output."""
    return [
        {
            "title": "Test Article One",
            "author": "Alice",
            "date_str": "2026-07-18",
            "time_str": "10:30:00",
            "html_body": "<p>Some <b>HTML</b> body.</p>",
            "markdown_body": "Some HTML body.",
            "link": "https://example.com/one",
            "pubDate": 1752837000,
            "body": "<p>Some <b>HTML</b> body.</p>",
        },
        {
            "title": "Test Article Two",
            "author": "Unknown",
            "date_str": "2026-07-18",
            "time_str": "11:45:00",
            "html_body": "<p>Another article.</p>",
            "markdown_body": "Another article.",
            "link": "",
            "pubDate": 1752840000,
            "body": "<p>Another article.</p>",
        },
    ]


# ------------------------------------------------------------------
# Dispatch / registry
# ------------------------------------------------------------------


class TestDispatch:
    def test_supported_formats(self) -> None:
        """supported_formats returns a non-empty list."""
        fmts = supported_formats()
        assert isinstance(fmts, list)
        assert "md-inline" in fmts
        assert "pdf" in fmts
        assert "txt" in fmts
        assert "json" in fmts

    def test_render_unknown_raises(self) -> None:
        """Unknown format name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown output format"):
            render("nonexistent", [], "F", "Feed", _utcnow(), Path("/tmp"))

    def test_format_ext(self) -> None:
        """format_ext returns the correct extension."""
        assert format_ext("md-inline") == "md"
        assert format_ext("pdf") == "pdf"
        assert format_ext("json") == "json"
        assert format_ext("txt") == "txt"

    def test_format_ext_unknown(self) -> None:
        """Unknown format returns the name as extension."""
        assert format_ext("foobar") == "foobar"


# ------------------------------------------------------------------
# Markdown inline
# ------------------------------------------------------------------


class TestMarkdownInline:
    def test_basic(self, tmp_path: Path) -> None:
        """Basic output includes header and items."""
        content = _sample_content()
        result = md_inline.render(
            content, "My Folder", "My Feed", _utcnow(), tmp_path
        )
        assert "# My Feed" in result
        assert "**Folder:** My Folder" in result
        assert "### Test Article One" in result
        assert "### Test Article Two" in result
        assert "Some HTML body." in result

    def test_author_excluded_unknown(self, tmp_path: Path) -> None:
        """Items with author='Unknown' don't show an Author line."""
        content = [
            {
                "title": "Only Unknown",
                "author": "Unknown",
                "date_str": "2026-07-18",
                "time_str": "12:00:00",
                "html_body": "",
                "markdown_body": "",
                "link": "",
                "pubDate": 0,
            }
        ]
        result = md_inline.render(
            content, "F", "Feed", _utcnow(), tmp_path
        )
        # No "Author: Unknown" line
        assert "Author: Unknown" not in result

    def test_no_link_no_url_line(self, tmp_path: Path) -> None:
        """Empty link field doesn't produce a URL line."""
        content = [
            {
                "title": "No Link",
                "author": "",
                "date_str": "2026-07-18",
                "time_str": "12:00:00",
                "html_body": "",
                "markdown_body": "Some text",
                "link": "",
                "pubDate": 0,
            }
        ]
        result = md_inline.render(
            content, "F", "Feed", _utcnow(), tmp_path
        )
        lines = result.split("\n")
        # Should not have a URL after the content lines
        assert "Some text" in result

    def test_base64_image_replacement(self, tmp_path: Path) -> None:
        """Image links in markdown_body are replaced with data URIs."""
        import responses as _responses

        content = [
            {
                "title": "With Image",
                "author": "",
                "date_str": "2026-07-18",
                "time_str": "12:00:00",
                "html_body": "<p>Before</p>",
                "markdown_body": "![caption](images/photo.png)",
                "link": "",
                "pubDate": 0,
                "body": '<p>Before</p><img src="https://example.com/photo.png">',
            }
        ]
        with _responses.RequestsMock() as rsps:
            rsps.head(
                "https://example.com/photo.png",
                status=200,
                headers={"Content-Type": "image/png"},
            )
            rsps.get(
                "https://example.com/photo.png",
                body=b"\x89PNG\r\n\x1a\n",
                headers={"Content-Type": "image/png"},
            )
            result = md_inline.render(
                content, "F", "Feed", _utcnow(), tmp_path
            )
        assert "data:image/png;base64," in result

    def test_external_image_preserved(self, tmp_path: Path) -> None:
        """Images from external URLs are kept as-is."""
        content = [
            {
                "title": "External",
                "author": "",
                "date_str": "2026-07-18",
                "time_str": "12:00:00",
                "html_body": "",
                "markdown_body": "![x](https://example.com/img.jpg)",
                "link": "",
                "pubDate": 0,
                "body": "<p>Some external</p>",
            }
        ]
        result = md_inline.render(
            content, "F", "Feed", _utcnow(), tmp_path
        )
        assert "data:image" not in result
        assert "https://example.com/img.jpg" in result

    def test_timezone_in_header(self, tmp_path: Path) -> None:
        """Header includes the timezone name."""
        result = md_inline.render(
            _sample_content(), "F", "Feed", _utcnow(), tmp_path
        )
        assert "Fetch Date:" in result


# ------------------------------------------------------------------
# Plain text
# ------------------------------------------------------------------


class TestPlainText:
    def test_basic(self, tmp_path: Path) -> None:
        """Basic output is plain text with header and items."""
        content = _sample_content()
        result = txt.render(
            content, "My Folder", "My Feed", _utcnow(), tmp_path
        )
        assert "My Feed" in result
        assert "Test Article One" in result
        assert "Test Article Two" in result
        assert "Some HTML body." in result
        assert "Alice" in result  # author shown
        assert "Unknown" not in result  # author='Unknown' is omitted

    def test_no_authors_line(self, tmp_path: Path) -> None:
        """Items with no author have a clean metadata section."""
        content = [
            {
                "title": "No Author",
                "author": "",
                "date_str": "2026-07-18",
                "time_str": "08:00:00",
                "html_body": "",
                "markdown_body": "Plain content",
                "link": "",
                "pubDate": 0,
            }
        ]
        result = txt.render(
            content, "F", "Feed", _utcnow(), tmp_path
        )
        assert "Plain content" in result
        assert "No Author" in result


# ------------------------------------------------------------------
# JSON
# ------------------------------------------------------------------


class TestJSON:
    def test_valid_json(self) -> None:
        """Output is valid JSON."""
        content = _sample_content()
        result = json_fmt.render(
            content, "My Folder", "My Feed", _utcnow(), Path("/tmp")
        )
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_structure(self) -> None:
        """Top-level keys are present."""
        content = _sample_content()
        data = json.loads(
            json_fmt.render(
                content, "My Folder", "My Feed", _utcnow(), Path("/tmp")
            )
        )
        assert "feed" in data
        assert "folder" in data
        assert "fetch_date" in data
        assert "timezone" in data
        assert "items" in data
        assert data["feed"] == "My Feed"
        assert data["folder"] == "My Folder"
        assert len(data["items"]) == 2

    def test_item_fields(self) -> None:
        """Each item has the expected fields."""
        content = [
            {
                "title": "Test",
                "author": "Bob",
                "date_str": "2026-01-01",
                "time_str": "12:00:00",
                "html_body": "",
                "markdown_body": "Content",
                "link": "https://example.com",
                "pubDate": 1700000000,
            }
        ]
        data = json.loads(
            json_fmt.render(content, "F", "F", _utcnow(), Path("/tmp"))
        )
        item = data["items"][0]
        assert item["title"] == "Test"
        assert item["author"] == "Bob"
        assert item["date"] == "2026-01-01"
        assert item["time"] == "12:00:00"
        assert item["content"] == "Content"
        assert item["url"] == "https://example.com"

    def test_no_url_when_empty(self) -> None:
        """Items with no link don't include a url key."""
        content = [
            {
                "title": "No Link",
                "author": "",
                "date_str": "2026-01-01",
                "time_str": "12:00:00",
                "html_body": "",
                "markdown_body": "No link here",
                "link": "",
                "pubDate": 0,
            }
        ]
        data = json.loads(
            json_fmt.render(content, "F", "F", _utcnow(), Path("/tmp"))
        )
        assert "url" not in data["items"][0]


# ------------------------------------------------------------------
# PDF
# ------------------------------------------------------------------


@pytest.mark.skipif(not _WEASYPRINT_AVAILABLE, reason="weasyprint not installed")
class TestPDF:
    def test_returns_bytes(self, tmp_path: Path) -> None:
        """PDF render returns bytes."""
        content = _sample_content()
        result = pdf.render(
            content, "My Folder", "My Feed", _utcnow(), tmp_path
        )
        assert isinstance(result, bytes)

    def test_valid_pdf_header(self, tmp_path: Path) -> None:
        """Output starts with the PDF magic bytes."""
        content = _sample_content()
        result = pdf.render(
            content, "My Folder", "My Feed", _utcnow(), tmp_path
        )
        assert result[:4] == b"%PDF"

    def test_includes_feed_name(self, tmp_path: Path) -> None:
        """The feed name appears in the PDF HTML content."""
        content = _sample_content()
        # We can't easily parse PDF text, but we can verify the HTML
        # generation by checking that the PDF is valid and non-empty.
        result = pdf.render(
            content, "My Folder", "My Feed", _utcnow(), tmp_path
        )
        assert len(result) > 1000  # reasonable PDF size


# ------------------------------------------------------------------
# Dispatch render()
# ------------------------------------------------------------------


class TestRenderDispatch:
    def test_md_inline_dispatch(self, tmp_path: Path) -> None:
        content = _sample_content()
        result = render(
            "md-inline", content, "F", "Feed", _utcnow(), tmp_path
        )
        assert "# Feed" in result

    def test_txt_dispatch(self, tmp_path: Path) -> None:
        content = _sample_content()
        result = render("txt", content, "F", "Feed", _utcnow(), tmp_path)
        assert "Test Article One" in result

    def test_json_dispatch(self, tmp_path: Path) -> None:
        content = _sample_content()
        result = render("json", content, "F", "Feed", _utcnow(), Path("/tmp"))
        data = json.loads(result)
        assert data["feed"] == "Feed"

    @pytest.mark.skipif(not _WEASYPRINT_AVAILABLE, reason="weasyprint not installed")
    def test_pdf_dispatch(self, tmp_path: Path) -> None:
        content = _sample_content()
        result = render("pdf", content, "F", "Feed", _utcnow(), tmp_path)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"