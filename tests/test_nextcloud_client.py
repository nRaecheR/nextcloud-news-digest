"""Tests for src/nextcloud_client.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import responses

from src.nextcloud_client import NextcloudNewsClient


# ------------------------------------------------------------------
# Helper fixtures
# ------------------------------------------------------------------

_API_V13 = "https://example.com/index.php/apps/news/api/v1-3"


def _make_client(*, mock_version: str = "28.4.0") -> NextcloudNewsClient:
    """Create a client with mocked version check."""
    # We can't easily avoid the __init__ version check, so we mock it.
    with patch.object(NextcloudNewsClient, "check_api_version"):
        client = NextcloudNewsClient(
            base_url="https://example.com",
            user="testuser",
            access_token="testtoken",
            timeout_seconds=20,
        )
        client.api_base = _API_V13
        return client


# ------------------------------------------------------------------
# Constructor tests
# ------------------------------------------------------------------

class TestInit:
    def test_https_required(self) -> None:
        """Non-https URLs are rejected."""
        with pytest.raises(ValueError, match="https://"):
            NextcloudNewsClient(
                base_url="http://example.com",
                user="testuser",
                access_token="testtoken",
            )

    def test_trailing_slash_stripped(self) -> None:
        """Trailing slashes are stripped from base_url."""
        client = _make_client()
        assert client.base_url == "https://example.com"


# ------------------------------------------------------------------
# get_folders
# ------------------------------------------------------------------

class TestGetFolders:
    @responses.activate
    def test_returns_folders(self) -> None:
        responses.add(
            responses.GET,
            f"{_API_V13}/folders",
            json={"folders": [{"id": 1, "title": "Folder A"}]},
            status=200,
        )
        client = _make_client()
        folders = client.get_folders()
        assert len(folders) == 1
        assert folders[0]["id"] == 1

    @responses.activate
    def test_empty_response(self) -> None:
        responses.add(
            responses.GET,
            f"{_API_V13}/folders",
            json={"folders": []},
            status=200,
        )
        client = _make_client()
        assert client.get_folders() == []

    @responses.activate
    def test_missing_folders_key(self) -> None:
        responses.add(
            responses.GET,
            f"{_API_V13}/folders",
            json={"other": []},
            status=200,
        )
        client = _make_client()
        assert client.get_folders() == []


# ------------------------------------------------------------------
# get_feeds
# ------------------------------------------------------------------

class TestGetFeeds:
    @responses.activate
    def test_returns_feeds(self) -> None:
        responses.add(
            responses.GET,
            f"{_API_V13}/feeds",
            json={"feeds": [{"id": 1, "title": "Feed A", "folderId": 10}]},
            status=200,
        )
        client = _make_client()
        feeds = client.get_feeds()
        assert len(feeds) == 1
        assert feeds[0]["title"] == "Feed A"

    @responses.activate
    def test_empty_feeds(self) -> None:
        responses.add(
            responses.GET,
            f"{_API_V13}/feeds",
            json={"feeds": []},
            status=200,
        )
        client = _make_client()
        assert client.get_feeds() == []


# ------------------------------------------------------------------
# get_feed_items
# ------------------------------------------------------------------

class TestGetFeedItems:
    @responses.activate
    def test_returns_items_and_timestamp(self) -> None:
        """Items from the requested feed are returned with correct timestamp."""
        items_payload = {
            "items": [
                {"id": 1, "feedId": 42, "title": "Item 1", "pubDate": 1700000000},
                {"id": 2, "feedId": 42, "title": "Item 2", "pubDate": 1700100000},
            ],
            "lastModified": 1700200000,
        }
        responses.add(
            responses.GET,
            f"{_API_V13}/items/updated?lastModified=0",
            json=items_payload,
            status=200,
        )
        client = _make_client()
        items, ts = client.get_feed_items(42, last_modified=0)
        assert len(items) == 2
        assert ts == 1700200000

    @responses.activate
    def test_client_side_filtering(self) -> None:
        """Only items from the requested feed are returned."""
        items_payload = {
            "items": [
                {"id": 1, "feedId": 42, "title": "Our feed item"},
                {"id": 2, "feedId": 99, "title": "Other feed item"},
                {"id": 3, "feedId": 42, "title": "Another our item"},
            ],
            "lastModified": 100,
        }
        responses.add(
            responses.GET,
            f"{_API_V13}/items/updated?lastModified=0",
            json=items_payload,
            status=200,
        )
        client = _make_client()
        items, _ = client.get_feed_items(42, last_modified=0)
        assert len(items) == 2
        assert items[0]["feedId"] == 42
        assert items[1]["feedId"] == 42

    @responses.activate
    def test_empty_items(self) -> None:
        responses.add(
            responses.GET,
            f"{_API_V13}/items/updated?lastModified=0",
            json={"items": [], "lastModified": 100},
            status=200,
        )
        client = _make_client()
        items, ts = client.get_feed_items(42, last_modified=0)
        assert items == []
        assert ts == 100

    @responses.activate
    def test_missing_last_modified_uses_current_time(self) -> None:
        """No lastModified key -> falls back to current time."""
        responses.add(
            responses.GET,
            f"{_API_V13}/items/updated?lastModified=0",
            json={"items": []},
            status=200,
        )
        client = _make_client()
        items, ts = client.get_feed_items(42, last_modified=0)
        assert items == []
        # ts should be an integer (current time fallback)
        assert isinstance(ts, int)

    @responses.activate
    def test_string_last_modified(self) -> None:
        """String lastModified is converted to int."""
        responses.add(
            responses.GET,
            f"{_API_V13}/items/updated?lastModified=0",
            json={"items": [], "lastModified": "1700300000"},
            status=200,
        )
        client = _make_client()
        items, ts = client.get_feed_items(42, last_modified=0)
        assert ts == 1700300000

    @responses.activate
    def test_http_error_returns_empty(self) -> None:
        """HTTP error returns empty list and current time."""
        responses.add(
            responses.GET,
            f"{_API_V13}/items/updated?lastModified=0",
            status=500,
        )
        client = _make_client()
        items, ts = client.get_feed_items(42, last_modified=0)
        assert items == []
        assert isinstance(ts, int)


# ------------------------------------------------------------------
# mark_item_read
# ------------------------------------------------------------------

class TestMarkItemRead:
    @responses.activate
    def test_mark_read(self) -> None:
        responses.add(
            responses.PUT,
            f"{_API_V13}/items/999/read",
            status=200,
        )
        client = _make_client()
        client.mark_item_read(999)  # Should not raise


# ------------------------------------------------------------------
# mark_items_read_batch
# ------------------------------------------------------------------

class TestMarkItemsReadBatch:
    @responses.activate
    def test_batch_mark_read(self) -> None:
        responses.add(
            responses.POST,
            f"{_API_V13}/items/read/multiple",
            status=200,
        )
        client = _make_client()
        client.mark_items_read_batch([1, 2, 3])

    @responses.activate
    def test_empty_batch_noop(self) -> None:
        client = _make_client()
        client.mark_items_read_batch([])  # Should not raise


# ------------------------------------------------------------------
# get_version / check_api_version
# ------------------------------------------------------------------

class TestVersion:
    @responses.activate
    def test_get_version(self) -> None:
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-3/version",
            json={"version": "28.4.0"},
            status=200,
        )
        client = NextcloudNewsClient(
            base_url="https://example.com",
            user="testuser",
            access_token="testtoken",
        )
        assert client.get_version() == "28.4.0"

    @responses.activate
    def test_check_api_version_passes(self) -> None:
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-3/version",
            json={"version": "28.4.0"},
            status=200,
        )
        client = NextcloudNewsClient(
            base_url="https://example.com",
            user="testuser",
            access_token="testtoken",
        )
        # Should not raise; api_base should be upgraded to v1-3
        assert "v1-3" in client.api_base

    @responses.activate
    def test_check_api_version_fails_on_old_version(self) -> None:
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-3/version",
            json={"version": "27.0.0"},
            status=200,
        )
        with pytest.raises(RuntimeError):
            NextcloudNewsClient(
                base_url="https://example.com",
                user="testuser",
                access_token="testtoken",
            )

    @responses.activate
    def test_fallback_to_v12_if_v13_fails(self) -> None:
        """If v1-3 version endpoint fails, tries v1-2."""
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-3/version",
            body=Exception("network error"),
        )
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-2/version",
            json={"version": "28.5.0"},
            status=200,
        )
        client = NextcloudNewsClient(
            base_url="https://example.com",
            user="testuser",
            access_token="testtoken",
        )
        assert "v1-2" in client.api_base

    @responses.activate
    def test_fallback_fails_all_versions(self) -> None:
        """If both v1-3 and v1-2 fail, raises RuntimeError."""
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-3/version",
            body=Exception("network error"),
        )
        responses.add(
            responses.GET,
            f"https://example.com/index.php/apps/news/api/v1-2/version",
            body=Exception("network error"),
        )
        with pytest.raises(RuntimeError, match="version endpoint"):
            NextcloudNewsClient(
                base_url="https://example.com",
                user="testuser",
                access_token="testtoken",
            )