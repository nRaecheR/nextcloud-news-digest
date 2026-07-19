"""Tests for src/images.py."""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
import responses

from src.images import (
    download_images,
    replace_images_in_html,
)


class TestDownloadImagesWithSrc:
    """Test downloading images from <img src="..."> tags."""

    @responses.activate
    def test_downloads_img_with_src(self, tmp_path: Path) -> None:
        """An <img src="..."> tag triggers a download."""
        url = "https://example.com/photo.jpg"
        responses.add(
            responses.HEAD,
            url,
            headers={"Content-Type": "image/jpeg", "Content-Length": "1024"},
            status=200,
        )
        responses.add(
            responses.GET,
            url,
            body=b"\x89PNG\r\n\x1a\n",
            status=200,
        )

        body = '<p>Hello <img src="https://example.com/photo.jpg" width="800" /></p>'
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 1
        assert "images/" in refs[0]["local_path"]
        assert refs[0]["alt"] == ""

    @responses.activate
    def test_downloads_protocol_relative_url(self, tmp_path: Path) -> None:
        """Protocol-relative URLs are resolved to https://."""
        url = "https://www.allmystery.de/i/abc123.jpg"
        responses.add(
            responses.HEAD,
            url,
            headers={"Content-Type": "image/jpeg"},
            status=200,
        )
        responses.add(
            responses.GET,
            url,
            body=b"\xff\xd8\xff\xe0",
            status=200,
        )

        body = '<img src="//www.allmystery.de/i/abc123.jpg" />'
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 1

    @responses.activate
    def test_skips_non_image_content_type(self, tmp_path: Path) -> None:
        """Files that are not images are skipped."""
        url = "https://example.com/document.pdf"
        responses.add(
            responses.HEAD,
            url,
            headers={"Content-Type": "application/pdf"},
            status=200,
        )

        body = '<img src="https://example.com/document.pdf" />'
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 0

    @responses.activate
    def test_skips_http_error(self, tmp_path: Path) -> None:
        """404 responses are skipped gracefully."""
        url = "https://example.com/missing.jpg"
        responses.add(
            responses.HEAD,
            url,
            status=404,
        )

        body = '<img src="https://example.com/missing.jpg" />'
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 0

    @responses.activate
    def test_deduplicates_same_url(self, tmp_path: Path) -> None:
        """The same URL appearing multiple times is downloaded once."""
        url = "https://example.com/photo.jpg"
        responses.add(
            responses.HEAD,
            url,
            headers={"Content-Type": "image/jpeg"},
            status=200,
        )
        responses.add(
            responses.GET,
            url,
            body=b"\x89PNG\r\n\x1a\n",
            status=200,
        )

        body = (
            '<img src="https://example.com/photo.jpg" />'
            '<img src="https://example.com/photo.jpg" />'
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 1


class TestDownloadImagesEmptyPlaceholder:
    """Test downloading images from empty <img alt="..."> placeholders."""

    @responses.activate
    def test_finds_href_in_following_link(self, tmp_path: Path) -> None:
        """An <img alt="..."> after an <a href="...media..."> downloads."""
        url = "https://example.com/photo.jpg"
        responses.add(
            responses.HEAD,
            url,
            headers={"Content-Type": "image/jpeg"},
            status=200,
        )
        responses.add(
            responses.GET,
            url,
            body=b"\x89PNG\r\n\x1a\n",
            status=200,
        )

        body = (
            '<img alt="Photo" width="800" height="600" /><br />'
            '<a href="https://example.com/photo.jpg">Source</a>'
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 1
        assert refs[0]["alt"] == "Photo"

    @responses.activate
    def test_ignores_non_media_href(self, tmp_path: Path) -> None:
        """Non-media URLs in <a> tags are ignored."""
        body = (
            '<img alt="Link" /><br />'
            '<a href="https://example.com/article">Article</a>'
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 0

    @responses.activate
    def test_skips_if_head_fails(self, tmp_path: Path) -> None:
        """A HEAD failure means no download."""
        url = "https://example.com/photo.jpg"
        responses.add(
            responses.HEAD,
            url,
            status=403,
        )

        body = (
            '<img alt="Photo" /><br />'
            '<a href="https://example.com/photo.jpg">Source</a>'
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        refs = download_images(body, output_dir)

        assert len(refs) == 0


class TestReplaceImagesInHtml:
    """Test replacing HTML image tags with markdown links."""

    def test_replaces_img_src(self) -> None:
        """An <img src="..."> tag is replaced with markdown syntax."""
        body = '<img src="https://example.com/photo.jpg" width="800" />'
        refs = [
            {
                "url": "https://example.com/photo.jpg",
                "local_path": "images/photo.jpg",
                "alt": "",
            }
        ]
        result = replace_images_in_html(body, refs)
        assert "![](images/photo.jpg)" in result

    def test_replaces_empty_img(self) -> None:
        """An empty <img alt="..."> tag is replaced with markdown syntax."""
        body = '<img alt="My Photo" width="800" />'
        refs = [
            {
                "url": "https://example.com/photo.jpg",
                "local_path": "images/photo.jpg",
                "alt": "My Photo",
            }
        ]
        result = replace_images_in_html(body, refs)
        assert '![My Photo](images/photo.jpg)' in result

    def test_removes_preceding_link(self) -> None:
        """A preceding <a> tag with the media URL is removed."""
        body = (
            '<br />\n'
            '<a href="https://example.com/photo.jpg">https://example.com/photo.jpg</a><br />\n'
        )
        refs = [
            {
                "url": "https://example.com/photo.jpg",
                "local_path": "images/photo.jpg",
                "alt": "Photo",
            }
        ]
        result = replace_images_in_html(body, refs)
        assert "https://example.com" not in result

    def test_no_refs_returns_original(self) -> None:
        """Empty refs list returns the original HTML."""
        body = "<p>Hello</p>"
        result = replace_images_in_html(body, [])
        assert result == body

    def test_multiple_images(self) -> None:
        """Multiple images are all replaced."""
        body = (
            '<img src="https://example.com/a.jpg" />'
            '<br />'
            '<img alt="B" width="100" />'
        )
        refs = [
            {
                "url": "https://example.com/a.jpg",
                "local_path": "images/a.jpg",
                "alt": "",
            },
            {
                "url": "https://example.com/b.jpg",
                "local_path": "images/b.jpg",
                "alt": "B",
            },
        ]
        result = replace_images_in_html(body, refs)
        assert "![](images/a.jpg)" in result
        assert '![B](images/b.jpg)' in result


class TestIntegration:
    """End-to-end tests combining download + replace + strip."""

    @responses.activate
    def test_full_pipeline(self, tmp_path: Path) -> None:
        """Download images, replace in HTML, then strip produces clean output."""
        url = "https://example.com/photo.jpg"
        responses.add(
            responses.HEAD,
            url,
            headers={"Content-Type": "image/jpeg"},
            status=200,
        )
        responses.add(
            responses.GET,
            url,
            body=b"\xff\xd8\xff\xe0",
            status=200,
        )

        body = (
            'A post about something. '
            '<img src="https://example.com/photo.jpg" width="800" /><br />'
            'More text after.'
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Download
        refs = download_images(body, output_dir)
        assert len(refs) == 1

        # Replace
        replaced = replace_images_in_html(body, refs)
        assert "![](images/" in replaced

        # Strip (like document.py does)
        import re as _re
        text = _re.sub(r"<[^>]+>", " ", replaced)
        text = _re.sub(r"\s+", " ", text).strip()

        # The stripped text should have the image reference intact
        assert "images/" in text
        # And the non-image content
        assert "A post about something" in text
        assert "More text after" in text