"""Validation for URLs."""


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

    _validate_url_pydantic(url)


def _validate_url_pydantic(url: str) -> None:
    """Validate a URL using Pydantic's validator."""
    from pydantic_core import SchemaValidator, core_schema

    SchemaValidator(
        core_schema.url_schema(
            allowed_schemes=["http", "https"],
            strict=True,
        )
    ).validate_python(url)
