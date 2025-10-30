from __future__ import annotations

from base64 import b64decode, b64encode
from typing import Any


def removeprefix(s: str, prefix: str) -> str:
    """Removes a prefix from a string.

    This roughly backports the built-in `str.removeprefix` function from Python 3.9+.
    Once Python 3.8 support is dropped, just replace this with `str.removeprefix`.
    """
    return s[len(prefix) :] if s.startswith(prefix) else s


def removesuffix(s: str, suffix: str) -> str:
    """Removes a suffix from a string.

    This roughly backports the built-in `str.removesuffix` function from Python 3.9+.
    Once Python 3.8 support is dropped, just replace this with `str.removesuffix`.
    """
    return s[: -len(suffix)] if s.endswith(suffix) else s


def ensureprefix(s: str, prefix: str) -> str:
    """Ensures the string has the given prefix prepended."""
    return s if s.startswith(prefix) else f"{prefix}{s}"


def ensuresuffix(s: str, suffix: str) -> str:
    """Ensures the string has the given suffix appended."""
    return s if s.endswith(suffix) else f"{s}{suffix}"


def nameof(obj: Any, full: bool = True) -> str:
    """Internal convenience helper that returns the object's `__name__` or `__qualname__`.

    If `full` is True, attempt to return the object's `__qualname__` attribute,
    falling back on the `__name__` attribute.
    """
    return getattr(obj, "__qualname__", obj.__name__) if full else obj.__name__


def b64decode_ascii(s: str) -> str:
    """Returns the decoded base64 string interpreted as ASCII.

    Convenience function for directly converting `str -> str`.
    """
    return b64decode(s).decode("ascii")


def b64encode_ascii(s: str) -> str:
    """Returns the base64 encoding of the string's ASCII bytes.

    Convenience function for directly converting `str -> str`.
    """
    return b64encode(s.encode("ascii")).decode("ascii")
