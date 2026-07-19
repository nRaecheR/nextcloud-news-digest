"""Configuration parser and validator for .env files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


_REQUIRED_KEYS = [
    "NEXTCLOUD_BASE_URL",
    "NEXTCLOUD_USER",
    "NEXTCLOUD_ACCESS_TOKEN",
    "NEWS_FOLDER",
    "NEWS_FEED",
]


class ConfigurationError(Exception):
    """Raised when required configuration values are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from environment."""

    base_url: str
    user: str
    access_token: str
    timeout_seconds: int
    news_folder: str
    news_feed: str
    state_mode: str
    state_file: Path
    days_per_file: int
    output_formats: list[str]


def load_settings(env_path: Optional[Path] = None) -> Settings:
    """Load and validate settings from environment variables.

    Parameters
    ----------
    env_path : Path, optional
        Optional path to a .env file.  If omitted, ``load_dotenv()``
        searches the current working directory.

    Returns
    -------
    Settings
        Validated application settings.

    Raises
    ------
    ConfigurationError
        If one or more required environment variables are missing or empty.
    """
    if env_path and env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    _OPTIONAL_KEYS = [
        ("REQUEST_TIMEOUT_SECONDS", 20),
        ("DAYS_PER_FILE", 7),
        ("OUTPUT_FORMATS", "md"),
        ("STATE_MODE", "mark_read"),
    ]

    _VALID_STATE_MODES = {"none", "file", "mark_read"}

    errors: list[str] = []
    vals: dict[str, str] = {}
    defaults: dict[str, int | str] = {}

    for key in _REQUIRED_KEYS:
        val = os.environ.get(key, "").strip()
        if not val:
            errors.append(f"Missing required env var: {key}")
        else:
            vals[key] = val

    for key, default in _OPTIONAL_KEYS:
        raw = os.environ.get(key, "").strip()
        if raw:
            vals[key] = raw
        else:
            defaults[key] = default

    if errors:
        raise ConfigurationError(
            f"Invalid .env configuration: {'; '.join(errors)}"
        )

    # Validate optional numeric fields
    try:
        timeout_val = int(vals.get("REQUEST_TIMEOUT_SECONDS") or defaults.get("REQUEST_TIMEOUT_SECONDS"))
        if timeout_val <= 0:
            raise ValueError()
    except ValueError:
        raise ConfigurationError("REQUEST_TIMEOUT_SECONDS must be a positive integer")

    try:
        days_val = int(vals.get("DAYS_PER_FILE") or defaults.get("DAYS_PER_FILE"))
        if days_val < 0:
            raise ValueError()
    except ValueError:
        raise ConfigurationError("DAYS_PER_FILE must be a non-negative integer (0 to disable splitting)")

    # Parse OUTPUT_FORMATS: comma-separated list of format names
    formats_str = vals.get(
        "OUTPUT_FORMATS", defaults.get("OUTPUT_FORMATS", "md")
    )
    if isinstance(formats_str, str):
        output_formats = [
            f.strip() for f in formats_str.split(",") if f.strip()
        ]
    else:
        output_formats = [formats_str]

    if not output_formats:
        raise ConfigurationError(
            "OUTPUT_FORMATS must contain at least one format (e.g. 'md,pdf')"
        )

    # Validate STATE_MODE
    state_mode = vals.get(
        "STATE_MODE", defaults.get("STATE_MODE", "mark_read")
    )
    if state_mode not in _VALID_STATE_MODES:
        raise ConfigurationError(
            f"STATE_MODE must be one of {sorted(_VALID_STATE_MODES)}, got '{state_mode}'"
        )

    return Settings(
        base_url=vals["NEXTCLOUD_BASE_URL"],
        user=vals["NEXTCLOUD_USER"],
        access_token=vals["NEXTCLOUD_ACCESS_TOKEN"],
        timeout_seconds=timeout_val,
        news_folder=vals["NEWS_FOLDER"],
        news_feed=vals["NEWS_FEED"],
        state_mode=state_mode,
        state_file=Path(".news-digest/state.json"),
        days_per_file=days_val,
        output_formats=output_formats,
    )