"""Tests for src/state.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.state import load_state, save_state


def _tmp_file() -> Path:
    """Create a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    import os

    os.close(fd)
    return Path(path)


class TestLoadState:
    """Tests for load_state."""

    def test_existing_file(self) -> None:
        """load_state returns data from a valid JSON file."""
        path = _tmp_file()
        try:
            save_state(path, 12345)
            state = load_state(path)
            assert state["last_fetched_timestamp"] == 12345
        finally:
            path.unlink(missing_ok=True)

    def test_missing_file_returns_defaults(self) -> None:
        """Missing file returns default state with timestamp 0."""
        state = load_state(Path("/nonexistent/path/state.json"))
        assert state["last_fetched_timestamp"] == 0

    def test_corrupted_json_returns_defaults(self) -> None:
        """Corrupted JSON returns default state."""
        path = _tmp_file()
        try:
            path.write_text("not valid json {{{")
            state = load_state(path)
            assert state["last_fetched_timestamp"] == 0
        finally:
            path.unlink(missing_ok=True)

    def test_empty_file_returns_defaults(self) -> None:
        """Empty file returns default state."""
        path = _tmp_file()
        try:
            path.write_text("")
            state = load_state(path)
            assert state["last_fetched_timestamp"] == 0
        finally:
            path.unlink(missing_ok=True)


class TestSaveState:
    """Tests for save_state."""

    def test_save_and_reload(self) -> None:
        """save_state writes valid JSON that can be reloaded."""
        path = _tmp_file()
        try:
            save_state(path, 99999)
            state = load_state(path)
            assert state["last_fetched_timestamp"] == 99999
        finally:
            path.unlink(missing_ok=True)

    def test_save_updates_timestamp(self) -> None:
        """save_state overwrites the previous timestamp."""
        path = _tmp_file()
        try:
            save_state(path, 11111)
            save_state(path, 22222)
            state = load_state(path)
            assert state["last_fetched_timestamp"] == 22222
        finally:
            path.unlink(missing_ok=True)

    def test_save_creates_parent_dir(self) -> None:
        """save_state creates parent directories if they don't exist."""
        tmpdir = Path(tempfile.mkdtemp())
        state_path = tmpdir / "nested" / "state.json"
        try:
            save_state(state_path, 42)
            state = load_state(state_path)
            assert state["last_fetched_timestamp"] == 42
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_save_produces_valid_json(self) -> None:
        """The saved file is valid JSON."""
        path = _tmp_file()
        try:
            save_state(path, 12345)
            with open(path) as f:
                data = json.load(f)
            assert data["last_fetched_timestamp"] == 12345
        finally:
            path.unlink(missing_ok=True)