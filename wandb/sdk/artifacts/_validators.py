"""Internal validation helper functions that are specific to artifacts."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Hashable, TypeVar

if TYPE_CHECKING:
    from typing import Collection


HashableT = TypeVar("HashableT", bound=Hashable)


def validate_aliases(aliases: Collection[str]) -> list[str]:
    """Validate the artifact aliases and return them as a list.

    Raises:
        ValueError: If any of the aliases contain invalid characters.
    """
    invalid_chars = ("/", ":")
    if any(char in alias for alias in aliases for char in invalid_chars):
        raise ValueError(
            f"Aliases must not contain any of the following characters: {', '.join(invalid_chars)}"
        )
    return list(aliases)


_VALID_TAG_PATTERN: re.Pattern[str] = re.compile(r"^[-\w]+( +[-\w]+)*$")


def validate_tags(tags: Collection[str]) -> list[str]:
    """Validate the artifact tag names and return them as a deduped list.

    In the case of duplicates, only keep the first tag, and otherwise maintain the order of appearance.

    Raises:
        ValueError: If any of the tags contain invalid characters.
    """
    if any(not _VALID_TAG_PATTERN.match(tag) for tag in tags):
        raise ValueError(
            "Invalid tag(s).  "
            "Tags must only contain alphanumeric characters separated by hyphens, underscores, and/or spaces."
        )
    return list(dict.fromkeys(tags))
