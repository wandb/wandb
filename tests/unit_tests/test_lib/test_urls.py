from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from wandb._pydantic import IS_PYDANTIC_V2
from wandb.sdk.lib import urls

_TEST_CASES: tuple[tuple[str, str | None], ...] = (
    ("https://api.wandb.ai", None),
    ("http://123.123.123.123", None),
    ("https://", "Invalid URL: 'https://'"),
    ("https://wandb.ai\t", "URL cannot contain unsafe characters"),
    ("https://wandb.ai\r", "URL cannot contain unsafe characters"),
    ("https://wandb.ai\n", "URL cannot contain unsafe characters"),
    ("file://wandb.ai", "URL must start with `http(s)://`"),
    (
        "https://wandb.ai\x00",
        r"'https://wandb.ai\x00' is not a valid server address",
    ),
)


@pytest.mark.parametrize("url, error", _TEST_CASES)
def test_validate_url_custom(url: str, error: str | None):
    if not error:
        urls._validate_url_custom(url)
    else:
        with pytest.raises(ValueError, match=re.escape(error)):
            urls._validate_url_custom(url)


@pytest.mark.parametrize("url, error", _TEST_CASES)
@pytest.mark.skipif(not IS_PYDANTIC_V2, reason="Requires Pydantic V2.")
def test_validate_url_pydantic(url: str, error: str | None):
    if not error:
        urls._validate_url_pydantic(url)
    else:
        # We don't test the exact error messages for Pydantic since they
        # depend on the Pydantic implementation, but we check that it agrees
        # whether the URLs are valid.
        with pytest.raises(ValueError):
            urls._validate_url_pydantic(url)


def test_uses_pydantic_if_available(monkeypatch: pytest.MonkeyPatch):
    mock_validate = MagicMock()
    monkeypatch.setattr(urls, "IS_PYDANTIC_V2", True)
    monkeypatch.setattr(urls, "_validate_url_pydantic", mock_validate)

    urls.validate_url("test URL")

    mock_validate.assert_called_once_with("test URL")


def test_uses_custom_validator(monkeypatch: pytest.MonkeyPatch):
    mock_validate = MagicMock()
    monkeypatch.setattr(urls, "IS_PYDANTIC_V2", False)
    monkeypatch.setattr(urls, "_validate_url_custom", mock_validate)

    urls.validate_url("test URL")

    mock_validate.assert_called_once_with("test URL")
