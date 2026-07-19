"""Tests for src/config.py."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.config import ConfigurationError, Settings, load_settings


class TestLoadSettings:
    """Tests for the load_settings function."""

    def _write_env(self, content: str) -> Path:
        """Write content to a temporary .env file and return its path."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        )
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    def _setup_env(self) -> dict[str, str]:
        """Return a dict of required env vars."""
        return {
            "NEXTCLOUD_BASE_URL": "https://example.com",
            "NEXTCLOUD_USER": "testuser",
            "NEXTCLOUD_ACCESS_TOKEN": "token123",
            "REQUEST_TIMEOUT_SECONDS": "30",
            "NEWS_FOLDER": "Test Folder",
            "NEWS_FEED": "Test Feed",
        }

    def test_valid_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid .env file produces correct Settings."""
        for k, v in self._setup_env().items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert isinstance(settings, Settings)
        assert settings.base_url == "https://example.com"
        assert settings.user == "testuser"
        assert settings.access_token == "token123"
        assert settings.timeout_seconds == 30
        assert settings.news_folder == "Test Folder"
        assert settings.news_feed == "Test Feed"
        assert settings.state_mode == "mark_read"  # default
        assert settings.state_file == Path(".news-digest/state.json")

    def test_custom_env_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A custom .env path is read correctly."""
        env_content = (
            "NEXTCLOUD_BASE_URL=https://custom.example.com\n"
            "NEXTCLOUD_USER=custom_user\n"
            "NEXTCLOUD_ACCESS_TOKEN=custom_token\n"
            "REQUEST_TIMEOUT_SECONDS=15\n"
            "NEWS_FOLDER=Custom Folder\n"
            "NEWS_FEED=Custom Feed\n"
        )
        env_path = self._write_env(env_content)
        monkeypatch.delenv("NEXTCLOUD_BASE_URL", raising=False)
        monkeypatch.delenv("NEXTCLOUD_USER", raising=False)
        monkeypatch.delenv("NEXTCLOUD_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("REQUEST_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("NEWS_FOLDER", raising=False)
        monkeypatch.delenv("NEWS_FEED", raising=False)
        settings = load_settings(env_path=env_path)
        assert settings.base_url == "https://custom.example.com"
        os.unlink(env_path)

    def test_missing_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing required env var raises ConfigurationError."""
        # Remove any env vars that previous tests may have left behind
        # so that load_dotenv() only reads from the temp .env file.
        for k in ("NEXTCLOUD_BASE_URL", "NEXTCLOUD_USER",
                   "NEXTCLOUD_ACCESS_TOKEN", "NEWS_FOLDER", "NEWS_FEED"):
            monkeypatch.delenv(k, raising=False)
        # Write a minimal .env with only one required var.
        env_content = "NEXTCLOUD_BASE_URL=https://example.com\n"
        env_path = self._write_env(env_content)
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_settings(env_path=env_path)
            assert "NEXTCLOUD_USER" in str(exc_info.value)
        finally:
            os.unlink(env_path)

    def test_empty_env_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty value for a required key raises ConfigurationError."""
        env = self._setup_env()
        env["NEWS_FOLDER"] = ""
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ConfigurationError):
            load_settings()

    def test_timeout_is_integer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """REQUEST_TIMEOUT_SECONDS is converted to int."""
        for k, v in self._setup_env().items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert isinstance(settings.timeout_seconds, int)
        assert settings.timeout_seconds == 30

    def test_env_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passing a non-existent path is ignored; env vars are used."""
        for k, v in self._setup_env().items():
            monkeypatch.setenv(k, v)
        non_existent = Path("/tmp/nonexistent_env_file_xyz.env")
        settings = load_settings(env_path=non_existent)
        assert settings.base_url == "https://example.com"

    def test_days_per_file_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DAYS_PER_FILE defaults to 7 when not set."""
        # Clear ALL env vars and use a minimal temp .env to avoid leaks from other tests
        for k in ("NEXTCLOUD_BASE_URL", "NEXTCLOUD_USER", "NEXTCLOUD_ACCESS_TOKEN",
                  "REQUEST_TIMEOUT_SECONDS", "NEWS_FOLDER", "NEWS_FEED",
                  "DAYS_PER_FILE", "OUTPUT_FORMATS", "STATE_MODE"):
            monkeypatch.delenv(k, raising=False)
        env_content = (
            "NEXTCLOUD_BASE_URL=https://example.com\n"
            "NEXTCLOUD_USER=testuser\n"
            "NEXTCLOUD_ACCESS_TOKEN=token123\n"
            "REQUEST_TIMEOUT_SECONDS=30\n"
            "NEWS_FOLDER=Test Folder\n"
            "NEWS_FEED=Test Feed\n"
        )
        env_path = self._write_env(env_content)
        try:
            settings = load_settings(env_path=env_path)
            assert settings.timeout_seconds == 30
            assert settings.days_per_file == 7
        finally:
            os.unlink(env_path)

    def test_days_per_file_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DAYS_PER_FILE can be set to a custom value."""
        for k, v in self._setup_env().items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("DAYS_PER_FILE", "14")
        settings = load_settings()
        assert settings.days_per_file == 14

    def test_output_formats_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OUTPUT_FORMATS defaults to ['md'] when not set."""
        # Use a minimal temp .env to avoid leaking from the real .env file
        env_content = (
            "NEXTCLOUD_BASE_URL=https://example.com\n"
            "NEXTCLOUD_USER=testuser\n"
            "NEXTCLOUD_ACCESS_TOKEN=token123\n"
            "REQUEST_TIMEOUT_SECONDS=30\n"
            "NEWS_FOLDER=Test Folder\n"
            "NEWS_FEED=Test Feed\n"
        )
        env_path = self._write_env(env_content)
        try:
            monkeypatch.delenv("OUTPUT_FORMATS", raising=False)
            monkeypatch.delenv("REQUEST_TIMEOUT_SECONDS", raising=False)
            monkeypatch.delenv("DAYS_PER_FILE", raising=False)
            settings = load_settings(env_path=env_path)
            assert settings.output_formats == ["md"]
        finally:
            os.unlink(env_path)

    def test_output_formats_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OUTPUT_FORMATS accepts comma-separated formats."""
        env = self._setup_env()
        monkeypatch.setenv("OUTPUT_FORMATS", "md,pdf,txt,json")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert settings.output_formats == ["md", "pdf", "txt", "json"]

    def test_output_formats_single(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OUTPUT_FORMATS with a single value works."""
        env = self._setup_env()
        monkeypatch.setenv("OUTPUT_FORMATS", "json")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert settings.output_formats == ["json"]

    def test_timeout_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """REQUEST_TIMEOUT_SECONDS with non-positive value raises."""
        env = self._setup_env()
        monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "0")
        for k, v in env.items():
            if k != "REQUEST_TIMEOUT_SECONDS":
                monkeypatch.setenv(k, v)
        with pytest.raises(ConfigurationError) as exc_info:
            load_settings()
        assert "REQUEST_TIMEOUT_SECONDS" in str(exc_info.value)

    def test_days_per_file_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DAYS_PER_FILE with non-positive value raises."""
        env = self._setup_env()
        monkeypatch.setenv("DAYS_PER_FILE", "-1")
        for k, v in env.items():
            if k != "DAYS_PER_FILE":
                monkeypatch.setenv(k, v)
        with pytest.raises(ConfigurationError) as exc_info:
            load_settings()
        assert "DAYS_PER_FILE" in str(exc_info.value)

    def test_state_mode_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STATE_MODE defaults to mark_read."""
        env = self._setup_env()
        monkeypatch.delenv("STATE_MODE", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert settings.state_mode == "mark_read"

    def test_state_mode_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STATE_MODE=none disables state tracking."""
        env = self._setup_env()
        env["STATE_MODE"] = "none"
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert settings.state_mode == "none"

    def test_state_mode_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STATE_MODE=file uses JSON file persistence."""
        env = self._setup_env()
        env["STATE_MODE"] = "file"
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert settings.state_mode == "file"

    def test_state_mode_mark_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STATE_MODE=mark_read marks items as read after fetch."""
        env = self._setup_env()
        env["STATE_MODE"] = "mark_read"
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = load_settings()
        assert settings.state_mode == "mark_read"

    def test_state_mode_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STATE_MODE with an invalid value raises ConfigurationError."""
        env = self._setup_env()
        env["STATE_MODE"] = "foobar"
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ConfigurationError) as exc_info:
            load_settings()
        assert "STATE_MODE" in str(exc_info.value)
        assert "foobar" in str(exc_info.value)
