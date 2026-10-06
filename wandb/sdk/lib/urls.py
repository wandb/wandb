"""Validation for URLs."""

from urllib.parse import urlsplit

from pydantic_core import SchemaValidator, core_schema

DEFAULT_BASE_URL = "https://api.forge.coreweave.com"

FORGE_API_PATH = "/api/wandb"
FORGE_APP_PATH = "/wandb"

FORGE_HOSTS = {
    "forge.coreweave.com": "api.wandb.ai",
    "qa.forge.coreweave.com": "api.qa.wandb.ai",
}
"""Maps each CoreWeave Forge host to the W&B API host behind it.

The API is served at the root of the Forge host's `api.` subdomain and of
the W&B API host, and proxied under FORGE_API_PATH on the Forge host.
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
    """Returns the CoreWeave Forge host serving the W&B deployment at the URL, if any."""
    hostname = urlsplit(url).hostname
    for forge, api in FORGE_HOSTS.items():
        if hostname in (forge, f"api.{forge}", api):
            return forge
    return None


def is_forge_host(url: str) -> bool:
    """Returns whether the URL points to a CoreWeave Forge host."""
    return forge_host(url) is not None


def forge_upstream_url(url: str) -> str:
    """Returns the W&B API URL behind a CoreWeave Forge URL, or the URL as is."""
    if host := forge_host(url):
        return f"https://{FORGE_HOSTS[host]}"
    return url


def normalize_forge_base_url(url: str) -> str:
    """Returns the direct API address for a Forge proxy URL, or the URL as is.

    Raises:
        ValueError: If the URL is on a Forge host but is not its W&B API proxy.
    """
    parsed = urlsplit(url)
    if parsed.hostname not in FORGE_HOSTS:
        return url
    if (
        parsed.scheme == "https"
        and parsed.port is None
        and parsed.path.rstrip("/") == FORGE_API_PATH
    ):
        return f"https://api.{parsed.hostname}"
    raise ValueError(
        f"Invalid Forge server address; use https://api.{parsed.hostname}."
    )
