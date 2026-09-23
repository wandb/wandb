from __future__ import annotations

import pytest
from wandb.sdk.lib import urls

_TEST_CASES: tuple[tuple[str, bool], ...] = (
    ("https://api.wandb.ai", True),
    ("http://123.123.123.123", True),
    ("https://", False),
    ("https://wandb.ai\t", False),
    ("https://wandb.ai\r", False),
    ("https://wandb.ai\n", False),
    ("file://wandb.ai", False),
    ("https://wandb.ai\x00", False),
)


@pytest.mark.parametrize("url, is_valid", _TEST_CASES)
def test_validate_url(url: str, is_valid: bool):
    if is_valid:
        urls.validate_url(url)
    else:
        with pytest.raises(ValueError):
            urls.validate_url(url)


def test_validate_url_requires_string():
    with pytest.raises(TypeError, match="Expected a string"):
        urls.validate_url(123)


@pytest.mark.parametrize(
    "url",
    [
        "https://forge.coreweave.com",
        "https://forge.coreweave.com/wandb",
        "http://forge.coreweave.com/api/wandb",
    ],
)
def test_validate_forge_base_url(url: str):
    with pytest.raises(ValueError, match=urls.DEFAULT_BASE_URL):
        urls.validate_forge_base_url(url)
