"""Validation for URLs."""

from urllib.parse import urlsplit

from pydantic_core import SchemaValidator, core_schema

DEFAULT_BASE_URL = "https://forge.coreweave.com/api/wandb"

FORGE_API_PATH = "/api/wandb"
FORGE_APP_PATH = "/wandb"

FORGE_HOSTS = {
    "forge.coreweave.com": "api.wandb.ai",
    "qa.forge.coreweave.com": "api.qa.wandb.ai",
}
"""Maps each CoreWeave Forge host to the W&B API host behind it.

The API is proxied under FORGE_API_PATH on the Forge host and also served
at the root of its `api.` subdomain.
"""

_URL_VALIDATOR = SchemaValidator(
    core_schema.url_schema(
        allowed_schemes=["http", "https"],
        strict=True,
    )
)


def validate_url(url: object) -> None:
    """Validate a URL.

    Args:
        url: The URL to validate.

    Raises:
        ValueError: If the URL is invalid.
        TypeError: If given something other than a string.
    """
    if not isinstance(url, str):
        raise TypeError(f"Expected a string, got {type(url)}")

    _URL_VALIDATOR.validate_python(url)


def forge_host(url: str) -> str | None:
    """Returns the CoreWeave Forge host the URL points to, if any."""
    hostname = (urlsplit(url).hostname or "").removeprefix("api.")
    return hostname if hostname in FORGE_HOSTS else None


def is_forge_host(url: str) -> bool:
    """Returns whether the URL points to a CoreWeave Forge host."""
    return forge_host(url) is not None


def forge_upstream_url(url: str) -> str:
    """Returns the W&B API URL behind a CoreWeave Forge URL, or the URL as is."""
    if host := forge_host(url):
        return f"https://{FORGE_HOSTS[host]}"
    return url


def validate_forge_base_url(url: str) -> None:
    """Require Forge server URLs to use the W&B API path over HTTPS.

    Raises:
        ValueError: If the URL is on a Forge host but is not its W&B API URL.
    """
    parsed = urlsplit(url)
    if parsed.hostname in FORGE_HOSTS and (
        parsed.scheme != "https"
        or parsed.port is not None
        or parsed.path.rstrip("/") != FORGE_API_PATH
    ):
        raise ValueError(
            "Invalid Forge server address;"
            f" use https://{parsed.hostname}{FORGE_API_PATH}."
        )
