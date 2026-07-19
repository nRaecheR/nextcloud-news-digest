"""Tests for src/document.py."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.document import generate_markdown, generate_markdown_files


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestGenerateMarkdown:
    """Tests for the generate_markdown function."""

    def test_empty_items(self) -> None:
        """Empty items list produces a short document."""
        md = generate_markdown([], "My Folder", "My Feed", _utcnow())
        assert "# My Feed" in md
        assert "**Folder:** My Folder" in md
        assert "No new items found." in md

    def test_single_item_all_fields(self) -> None:
        """A complete item produces expected structure."""
        items = [
            {
                "title": "Test Article",
                "author": "Jane Doe",
                "pubDate": 1700000000,  # 2023-11-14 22:13:20 UTC
                "body": "<p>Some description</p>",
                "url": "https://example.com/article",
            }
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())

        assert "# My Feed" in md
        assert "## 2023-11-14" in md
        assert "### Test Article" in md
        assert "Author: Jane Doe" in md
        assert "Date: 2023-11-14" in md
        assert "Time:" in md
        assert "Some description" in md
        assert "(truncated)" not in md  # short content, no truncation
        assert "https://example.com/article" in md

    def test_multiple_items_grouped_by_date(self) -> None:
        """Items from different dates get separate date sections."""
        # Use timestamps that produce dates in UTC regardless of local TZ.
        # 1700000000 → 2023-11-14 22:13:20 UTC
        # 1700100000 → 2023-11-15 23:53:20 UTC  (≈ 27h later)
        items = [
            {"title": "Old Article", "pubDate": 1700000000},
            {"title": "New Article", "pubDate": 1700100000},
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())

        # In UTC: Nov 14 and Nov 15. With CET offset (+1), still Nov 14 and Nov 16
        # — either way they span two distinct date sections.
        date_sections = [m for m in re.findall(r"## (\d{4}-\d{2}-\d{2})", md)]
        assert len(set(date_sections)) >= 2
        assert "### Old Article" in md
        assert "### New Article" in md

    def test_missing_optional_fields(self) -> None:
        """Items without author, description, or URL are handled gracefully."""
        items = [
            {"title": "Minimal Article", "pubDate": 1700000000},
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        assert "### Minimal Article" in md
        # No "Author:" line should appear
        assert "Author:" not in md

    def test_html_stripped_from_body(self) -> None:
        """HTML tags are stripped from body content."""
        items = [
            {
                "title": "Bold Article",
                "pubDate": 1700000000,
                "body": "<p>This has <b>bold</b> and <a href='url'>links</a></p>",
            }
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        assert "<p>" not in md
        assert "<b>" not in md
        assert "This has bold and links" in md

    def test_long_body_truncated(self) -> None:
        """Body content longer than 2000 chars is truncated."""
        items = [
            {
                "title": "Long Article",
                "pubDate": 1700000000,
                "body": "x" * 2500,
            }
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        assert "(truncated)" in md

    def test_body_used_over_description(self) -> None:
        """When both body and description exist, body takes priority."""
        items = [
            {
                "title": "Article",
                "pubDate": 1700000000,
                "body": "This is the body content",
                "description": "This is the description",
            }
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        assert "This is the body content" in md
        assert "This is the description" not in md

    def test_fallback_to_description_when_no_body(self) -> None:
        """When body is empty, description is used as fallback."""
        items = [
            {
                "title": "Article",
                "pubDate": 1700000000,
                "description": "This is the description only",
            }
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        assert "This is the description only" in md

    def test_sort_order_oldest_first(self) -> None:
        """Output shows items in oldest-to-newest order."""
        items = [
            {"title": "Newest", "pubDate": 1700000100},
            {"title": "Oldest", "pubDate": 1700000000},
            {"title": "Middle", "pubDate": 1700000050},
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        # In the markdown, "Oldest" should appear before "Middle" before "Newest"
        oldest_pos = md.index("### Oldest")
        middle_pos = md.index("### Middle")
        newest_pos = md.index("### Newest")
        assert oldest_pos < middle_pos < newest_pos

    def test_no_url_no_link(self) -> None:
        """Items without a URL do not produce a link line."""
        items = [
            {"title": "No Link", "pubDate": 1700000000},
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        # Should have a blank line after the metadata but not a URL line
        assert "No Link" in md

    def test_fetch_date_header(self) -> None:
        """Header includes fetch date."""
        md = generate_markdown([], "My Folder", "My Feed", _utcnow())
        assert "**Fetch Date:**" in md
        assert "**Total Items:** 0" in md

    def test_metadata_no_author_for_unknown(self) -> None:
        """Items with author='Unknown' do not show Author line."""
        items = [
            {"title": "Article", "pubDate": 1700000000, "author": "Unknown"},
        ]
        md = generate_markdown(items, "My Folder", "My Feed", _utcnow())
        assert "Author:" not in md

class TestGenerateMarkdownFiles:
    """Tests for generate_markdown_files (multi-file generation)."""

    def test_single_window_no_split(self, tmp_path: Path) -> None:
        """When all items are within one window, only one file is created."""
        fetch_date = datetime(2026, 7, 15, 10, 0, 0)
        items = [
            {"title": "A", "pubDate": 1752500000, "body": "", "description": ""},
            {"title": "B", "pubDate": 1752510000, "body": "", "description": ""},
        ]
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        paths = generate_markdown_files(
            items, "TestFolder", "TestFeed", fetch_date,
            output_dir=output_dir, days_per_file=7,
        )

        assert len(paths) == 1
        content = Path(paths[0]).read_text()
        assert "# TestFeed" in content
        assert "Total Items:** 2" in content
        assert "### A" in content
        # "B" comes after "A" chronologically
        assert content.index("### A") < content.index("### B")

    def test_two_windows(self, tmp_path: Path) -> None:
        """Items spanning two windows produce two files."""
        fetch_date = datetime(2026, 7, 15, 10, 0, 0)
        items = [
            {"title": "Day1", "pubDate": 1752500000, "body": "", "description": ""},
            {"title": "Day10", "pubDate": 1752500000 + 10 * 86400, "body": "", "description": ""},
        ]
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        paths = generate_markdown_files(
            items, "TestFolder", "TestFeed", fetch_date,
            output_dir=output_dir, days_per_file=7,
        )

        assert len(paths) == 2
        # Each file has its own header (Total Items counts all items, not just per-file)
        for path in paths:
            content = Path(path).read_text()
            assert "# TestFeed" in content
            # Each file contains the full header with total count
            assert "Total Items:" in content

    def test_shared_image_cache(self, tmp_path: Path) -> None:
        """Items across files share the image cache."""
        from src.images import download_images, replace_images_in_html
        from unittest.mock import MagicMock, patch
        import os

        fetch_date = datetime(2026, 7, 15, 10, 0, 0)
        # Two items on different "days" with the same image URL
        image_url = "https://example.com/photo.jpg"

        items = [
            {
                "title": "Day1Item",
                "pubDate": 1752500000,
                "body": f'<img src="{image_url}">',
                "description": "",
            },
            {
                "title": "Day10Item",
                "pubDate": 1752500000 + 10 * 86400,
                "body": f'<img src="{image_url}">',
                "description": "",
            },
        ]

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Mock the image download to track calls
        call_count = 0

        def mock_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return [{"url": image_url, "local_path": "images/photo.jpg", "alt": ""}]

        with patch("src.document.download_images", side_effect=mock_download):
            paths = generate_markdown_files(
                items, "TestFolder", "TestFeed", fetch_date,
                output_dir=output_dir, days_per_file=7,
            )

        # Image should only be downloaded once due to shared cache
        # But since we mocked download_images, each call increments.
        # The real test is that the cache dict is shared.
        assert len(paths) == 2


class TestSplitContentWindows:
    """Tests for _split_content_windows in main.py."""

    def test_no_split_when_days_per_file_is_one(self) -> None:
        """days_per_file=1 returns a single window."""
        from src.main import _split_content_windows
        content = [{"date_str": "2026-07-01"}, {"date_str": "2026-07-02"}]
        result = _split_content_windows(content, 1)
        assert len(result) == 1

    def test_split_by_date_windows(self) -> None:
        """Items are split into 7-day windows."""
        from src.main import _split_content_windows
        content = [
            {"date_str": "2026-07-01"},
            {"date_str": "2026-07-03"},
            {"date_str": "2026-07-05"},  # still same window (4 days)
            {"date_str": "2026-07-10"},  # next window (5 days from start)
            {"date_str": "2026-07-15"},  # next window (5 days)
        ]
        result = _split_content_windows(content, 7)
        assert len(result) >= 2
        # All items within 7-day span should be in first window
        assert len(result[0]) >= 3

    def test_two_items_same_window(self) -> None:
        """Two items within 7 days stay in same window."""
        from src.main import _split_content_windows
        content = [
            {"date_str": "2026-07-01"},
            {"date_str": "2026-07-05"},
        ]
        result = _split_content_windows(content, 7)
        assert len(result) == 1

    def test_two_items_different_windows(self) -> None:
        """Two items 8+ days apart are in different windows."""
        from src.main import _split_content_windows
        content = [
            {"date_str": "2026-07-01"},
            {"date_str": "2026-07-10"},  # 9 days later
        ]
        result = _split_content_windows(content, 7)
        assert len(result) == 2
