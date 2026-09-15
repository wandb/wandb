"""Validation for URLs."""

from urllib.parse import urlsplit

from pydantic_core import SchemaValidator, core_schema

FORGE_API_PATH = "/api/wandb"
FORGE_APP_PATH = "/wandb"
_FORGE_HOSTS = frozenset({"forge.coreweave.com", "qa.forge.coreweave.com"})

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


def is_forge_host(url: str) -> bool:
    """Return whether a URL uses a supported Forge host and HTTPS port."""
    parsed = urlsplit(url)
    return (
        parsed.hostname in _FORGE_HOSTS
        and parsed.port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def validate_forge_base_url(url: str) -> None:
    """Require Forge API URLs to use the W&B API proxy over HTTPS.

    Other hosts are unaffected. Call `validate_url` first for general URL
    validation.
    """
    parsed = urlsplit(url)
    if parsed.hostname not in _FORGE_HOSTS:
        return

    if (
        parsed.scheme != "https"
        or not is_forge_host(url)
        or parsed.path.rstrip("/") != FORGE_API_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Invalid Forge server address; use "
            f"https://{parsed.hostname}{FORGE_API_PATH}."
        )
