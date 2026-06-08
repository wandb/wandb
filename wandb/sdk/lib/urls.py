"""Validation for URLs."""

from pydantic_core import SchemaValidator, core_schema

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
