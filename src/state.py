"""Persistent state management for timestamp tracking."""

from __future__ import annotations

import json
from pathlib import Path


_DEFAULT_STATE: dict[str, int] = {"last_fetched_timestamp": 0}


def load_state(path: Path) -> dict[str, int]:
    """Load persisted state from a JSON file.

    Returns the default state (timestamp 0) when the file is missing
    or contains invalid JSON so that callers can fall back gracefully.

    Parameters
    ----------
    path : Path
        Path to the state JSON file.

    Returns
    -------
    dict[str, int]
        State dictionary containing at least ``last_fetched_timestamp``.
    """
    if path.is_file():
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict) and "last_fetched_timestamp" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_STATE)


def save_state(path: Path, timestamp: int) -> None:
    """Save the current fetch timestamp to the state file.

    Creates parent directories if they do not exist.

    Parameters
    ----------
    path : Path
        Path to the state JSON file.
    timestamp : int
        The last-fetched epoch timestamp to persist.
    """
    state = load_state(path)
    state["last_fetched_timestamp"] = timestamp

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)