"""Internal helper functions for artifacts."""
from __future__ import annotations

from typing import Collection


def validate_aliases(aliases: Collection[str]) -> list[str]:
    """
    Validate the given artifact aliases, returning them as a list if successful.

    Raises:
        ValueError: If any of the aliases contain invalid characters.
    """
    invalid_chars = ("/", ":")
    if any(char in alias for alias in aliases for char in invalid_chars):
        raise ValueError(
            f"Aliases must not contain any of the following characters: {', '.join(invalid_chars)}"
        )
    return list(aliases)
