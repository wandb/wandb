"""Validation for API keys."""

from __future__ import annotations

import re


def check_api_key(key: str) -> str | None:
    """Returns text describing problems with the API key, or None.

    If the key is in a valid format, returns None. Otherwise, returns
    a string formatted as a complete sentence (capitalized, punctuated)
    explaining the problem with the key.

    Args:
        key: The API key to check.
    """
    if not key:
        return "API key is empty."

    # On-prem API keys have a variable-length prefix followed by a dash.
    parts = key.rsplit("-", 1)
    if len(parts) == 1:
        secret = parts[0]
    else:
        _, secret = parts

    if not re.fullmatch(r"\w+", secret):
        return "API key may only contain the letters A-Z, digits and underscores."

    if (secret_len := len(secret)) < 40:
        return f"API key must have 40+ characters, has {secret_len}."

    return None
