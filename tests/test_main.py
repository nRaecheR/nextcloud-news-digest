"""Integration tests for src/main.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dataclasses import replace

from src.config import Settings
from src.main import _mark_items_read, main


class TestMarkItemsRead:
    """Tests for the _mark_items_read helper."""

    def test_marks_items_as_read(self) -> None:
        """Valid item IDs are passed to the batch endpoint."""
        client = MagicMock()
        items = [
            {"id": 1, "title": "A"},
            {"id": 2, "title": "B"},
        ]
        _mark_items_read(client, items)
        client.mark_items_read_batch.assert_called_once_with([1, 2])

    def test_empty_items_noop(self) -> None:
        """No items -> no API call."""
        client = MagicMock()
        _mark_items_read(client, [])
        client.mark_items_read_batch.assert_not_called()

    def test_items_without_id_skipped(self) -> None:
        """Items missing the id key are skipped (no API call)."""
        client = MagicMock()
        items = [{"title": "A"}, {"title": "B", "no_id": True}]
        _mark_items_read(client, items)
        client.mark_items_read_batch.assert_not_called()

    def test_mark_read_failure_logged(self) -> None:
        """API failure logs a warning but does not raise."""
        client = MagicMock()
        client.mark_items_read_batch.side_effect = Exception("API error")
        items = [{"id": 1}]
        # Should not raise
        _mark_items_read(client, items)
        # Still called, just fails
        client.mark_items_read_batch.assert_called_once_with([1])


class TestMainModeDispatch:
    """Tests for the mode-aware fetch loop in main()."""

    def _mock_settings(
        self, state_mode: str = "mark_read", days_per_file: int = 0
    ) -> Settings:
        """Return a Settings mock with the given state_mode."""
        return Settings(
            base_url="https://example.com",
            user="testuser",
            access_token="token",
            timeout_seconds=20,
            news_folder="Test Folder",
            news_feed="Test Feed",
            state_mode=state_mode,
            state_file=Path(".news-digest/state.json"),
            days_per_file=days_per_file,
            output_formats=["json"],
        )

    def _make_client(self, feed_id: int = 42, items: list[dict] | None = None) -> MagicMock:
        """Return a client mock that finds the feed and returns items."""
        if items is None:
            items = [
                {"id": 1, "feedId": feed_id, "title": "Item A", "body": "", "url": "https://example.com/1", "pubDate": 1700000000},
            ]
        client = MagicMock()
        client.get_folders.return_value = [{"id": 10, "title": "Test Folder"}]
        client.get_feeds.return_value = [{"id": feed_id, "folderId": 10, "title": "Test Feed"}]
        client.get_feed_items.return_value = (items, 1700100000)
        return client

    def test_state_mode_none_fetches_all(self) -> None:
        """state_mode=none always passes last_modified=0, no mark-as-read."""
        settings = self._mock_settings("none")
        client = self._make_client()
        items = [
            {"id": 1, "feedId": 42, "title": "A", "body": "", "url": "https://example.com/1", "pubDate": 1700000000},
        ]
        client.get_feed_items.return_value = (items, 1700100000)

        with patch("src.main.load_settings", return_value=settings):
            with patch("src.main.NextcloudNewsClient", return_value=client):
                with patch("src.main._write_output", return_value=[]):
                    result = main()

        assert result == 0
        # Verify last_modified=0 was used (no timestamp from state)
        client.get_feed_items.assert_called_once()
        call_kwargs = client.get_feed_items.call_args
        # Check keyword argument
        assert call_kwargs[1]["last_modified"] == 0
        # mark_items_read_batch should NOT be called
        client.mark_items_read_batch.assert_not_called()

    def test_state_mode_none_does_not_write_state(self) -> None:
        """state_mode=none never touches the state file on disk."""
        tmpdir = Path(tempfile.mkdtemp())
        state_file = tmpdir / ".news-digest" / "state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text('{"last_fetched_timestamp": 999}')

        settings = self._mock_settings("none")
        settings = replace(settings, state_file=state_file)

        items = [
            {"id": 1, "feedId": 42, "title": "A", "body": "", "url": "https://example.com/1", "pubDate": 1700000000},
        ]
        client = MagicMock()
        client.get_folders.return_value = [{"id": 10, "title": "Test Folder"}]
        client.get_feeds.return_value = [{"id": 42, "folderId": 10, "title": "Test Feed"}]
        client.get_feed_items.return_value = (items, 1700100000)

        with patch("src.main.load_settings", return_value=settings):
            with patch("src.main.NextcloudNewsClient", return_value=client):
                with patch("src.main._write_output", return_value=[]):
                    result = main()

        assert result == 0
        # State file must remain untouched (not created, not modified)
        assert state_file.exists()
        assert json.loads(state_file.read_text())["last_fetched_timestamp"] == 999

    def test_state_mode_mark_read_marks_as_read(self) -> None:
        """state_mode=mark_read fetches all and calls mark_items_read_batch."""
        settings = self._mock_settings("mark_read")
        items = [
            {"id": 1, "feedId": 42, "title": "A", "body": "", "url": "https://example.com/1", "pubDate": 1700000000},
        ]
        client = self._make_client()
        client.get_feed_items.return_value = (items, 1700100000)

        with patch("src.main.load_settings", return_value=settings):
            with patch("src.main.NextcloudNewsClient", return_value=client):
                with patch("src.main._write_output", return_value=[]):
                    result = main()

        assert result == 0
        # last_modified should be 0 (no state tracking)
        call_kwargs = client.get_feed_items.call_args
        assert call_kwargs[1]["last_modified"] == 0
        # Should mark items as read
        client.mark_items_read_batch.assert_called_once()
        call_args = client.mark_items_read_batch.call_args[0][0]
        assert 1 in call_args

    def test_state_mode_file_uses_state_file(self) -> None:
        """state_mode=file loads/saves timestamp from state file."""
        tmpdir = Path(tempfile.mkdtemp())
        state_file = tmpdir / "state.json"

        settings = self._mock_settings("file")
        settings = replace(settings, state_file=state_file)

        items = [
            {"id": 1, "feedId": 42, "title": "A", "body": "", "url": "https://example.com/1", "pubDate": 1700000000},
        ]
        client = self._make_client()
        client.get_feed_items.return_value = (items, 1700100000)

        with patch("src.main.load_settings", return_value=settings):
            with patch("src.main.NextcloudNewsClient", return_value=client):
                with patch("src.main._write_output", return_value=[]):
                    result = main()

        assert result == 0
        # State file should have been created
        assert state_file.exists()
        state_data = json.loads(state_file.read_text())
        assert state_data["last_fetched_timestamp"] == 1700100000
        # mark_items_read_batch should NOT be called in file mode
        client.mark_items_read_batch.assert_not_called()

    def test_state_mode_empty_items_noop(self) -> None:
        """No items fetched -> nothing written, no mark-as-read."""
        settings = self._mock_settings("mark_read")
        client = self._make_client()
        client.get_feed_items.return_value = ([], 1700100000)

        with patch("src.main.load_settings", return_value=settings):
            with patch("src.main.NextcloudNewsClient", return_value=client):
                with patch("src.main._write_output", return_value=[]):
                    result = main()

        assert result == 0
        client.mark_items_read_batch.assert_not_called()
        client.get_feed_items.assert_called_once()