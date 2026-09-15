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
    "url, expected",
    [
        ("https://forge.coreweave.com/api/wandb", True),
        ("https://qa.forge.coreweave.com/wandb", True),
        ("https://FORGE.COREWEAVE.COM:443/wandb", True),
        ("https://api.wandb.ai", False),
        ("https://coreweave.com", False),
        ("https://other.forge.coreweave.com", False),
        ("https://forged.coreweave.com", False),
        ("https://forge.coreweave.com.example.org", False),
        ("https://notforge.coreweave.com", False),
        ("https://forge.coreweave.com:8443", False),
        ("https://forge.coreweave.com@other.example", False),
        ("https://user@forge.coreweave.com", False),
    ],
)
def test_is_forge_host(url, expected):
    assert urls.is_forge_host(url) is expected


@pytest.mark.parametrize("host", ["forge.coreweave.com", "qa.forge.coreweave.com"])
@pytest.mark.parametrize("suffix", ["", "/", "//"])
def test_validate_forge_api_base_url(host, suffix):
    urls.validate_forge_base_url(f"https://{host}/api/wandb{suffix}")


@pytest.mark.parametrize(
    "url",
    [
        "https://forge.coreweave.com",
        "https://forge.coreweave.com/wandb",
        "https://forge.coreweave.com/api/wandb/graphql",
        "https://forge.coreweave.com/api/wandb?query=value",
        "https://forge.coreweave.com/api/wandb#fragment",
        "https://user@forge.coreweave.com/api/wandb",
        "https://forge.coreweave.com:8443/api/wandb",
        "http://forge.coreweave.com/api/wandb",
    ],
)
def test_rejects_invalid_forge_api_base_url(url):
    with pytest.raises(ValueError, match="https://forge.coreweave.com/api/wandb"):
        urls.validate_forge_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/custom",
        "https://api.wandb.ai",
        "https://api.wandb.io",
        "http://forge.coreweave.com.example.org",
        "https://custom.coreweave.com/api",
    ],
)
def test_forge_validation_preserves_other_hosts(url):
    urls.validate_forge_base_url(url)
