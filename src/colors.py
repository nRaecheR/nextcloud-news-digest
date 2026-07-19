"""ANSI color helpers for terminal output."""


def green(text: str) -> str:
    """Return text formatted in green."""
    return f"\033[32m{text}\033[0m"


def orange(text: str) -> str:
    """Return text formatted in orange/yellow."""
    return f"\033[33m{text}\033[0m"


def red(text: str) -> str:
    """Return text formatted in red."""
    return f"\033[31m{text}\033[0m"